"""Email-scraper job engine.

Wraps the compliant `scraper.extract_domain` (company's own public business pages,
same-domain published addresses only) as the core engine, and runs batches as
background jobs with live per-domain status, stop/resume/restart, dedup, email
validation, and CSV/XLSX export. Jobs are scoped by mode (vendor/client).

Dynamic Concurrency Scaling:
  1–100 domains → 20 workers
  101–500 → 35
  501–1000 → 50
  1001–5000 → 75
  5001–20000 → 100
  20001+ → 125 (capped by resources)
  Auto-decreases if CPU > 85% or RAM > 85%
"""
import csv
import io
import re
import threading
from datetime import datetime
from urllib.parse import urlparse

from .database import SessionLocal
from .crm_models import ScraperJob, ScraperJobDomain, ScraperResult
from . import scraper, compliance

_threads: dict[int, threading.Thread] = {}
# In-memory stop flags — checked on EVERY domain so Stop is instant, not batched.
_stop_flags: dict[int, bool] = {}


# Total worker budget shared across ALL running jobs. Kept modest on purpose:
# the same machine also serves the web UI, and saturating the CPU/network makes
# the dashboard unresponsive.
TOTAL_WORKER_BUDGET = 30


def _calc_workers(total_domains: int) -> int:
    """Adaptive workers: split the shared budget across all running jobs so
    multiple dashboards can scrape simultaneously without overloading.
      1 job  -> up to 50 workers
      2 jobs -> ~30 each
      3 jobs -> ~20 each
    Never fewer than 10 so each job still makes steady progress."""
    running = max(1, len([t for t in _threads.values() if t.is_alive()]))
    per_job = max(10, min(50, TOTAL_WORKER_BUDGET // running))
    # Don't spin up more workers than there are domains to process
    return min(per_job, max(1, total_domains))


def _check_resources() -> float:
    """Non-blocking resource check. Returns scaling factor 0.5–1.0."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)  # non-blocking (last sample)
        ram = psutil.virtual_memory().percent
        if cpu > 90 or ram > 90: return 0.5
        if cpu > 85 or ram > 85: return 0.7
        return 1.0
    except Exception:
        return 1.0


def _effective_workers(total_domains: int) -> int:
    """Calculate workers with resource-aware scaling."""
    base = _calc_workers(total_domains)
    factor = _check_resources()
    effective = max(5, int(base * factor))  # minimum 5 workers always
    return effective

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
JUNK_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def normalize_domain(raw: str) -> str:
    d = raw.strip().lower()
    if not d:
        return ""
    if "//" not in d:
        d = "https://" + d
    host = urlparse(d).netloc or urlparse(d).path
    return host.replace("www.", "").split("/")[0].strip()


def clean_email(e: str) -> str:
    return (e or "").strip().strip(".,;:<>()[]\"'").lower()


def valid_email(e: str) -> bool:
    return bool(EMAIL_RE.match(e)) and not e.endswith(JUNK_ENDINGS)


# ---------------- job creation ----------------

def create_job(db, mode: str, name: str, domains: list[str], source: str = "manual",
               max_per_domain: int = 2) -> ScraperJob:
    seen, clean_domains = set(), []
    for raw in domains:
        d = normalize_domain(raw)
        if d and d not in seen:
            seen.add(d)
            clean_domains.append(d)
    job = ScraperJob(mode=mode, name=name or f"Scrape {datetime.utcnow():%H:%M}",
                     source=source, status="queued", total=len(clean_domains),
                     max_per_domain=max(1, min(int(max_per_domain or 2), 10)))
    db.add(job); db.commit(); db.refresh(job)
    # Duplicate detection: check if domain was already scraped in a previous job (same mode)
    for d in clean_domains:
        prev = (db.query(ScraperJobDomain)
                .join(ScraperJob, ScraperJob.id == ScraperJobDomain.job_id)
                .filter(ScraperJob.mode == mode,
                        ScraperJobDomain.domain == d,
                        ScraperJobDomain.status.in_(["completed", "no_email"]))
                .first())
        is_dup = prev is not None
        db.add(ScraperJobDomain(job_id=job.id, domain=d, is_duplicate=is_dup))
    db.commit()
    return job


# ---------------- the worker ----------------


def _scrape_one(domain: str, mode: str = "vendor") -> dict:
    """Network only — safe to run in a thread (no DB access here)."""
    try:
        return scraper.extract_domain(domain, mode=mode)
    except Exception as e:
        return {"contacts": [], "status": f"error: {type(e).__name__}", "vendor_signals": {}}


def _save_result(db, job: ScraperJob, jd: ScraperJobDomain, result: dict, limit: int):
    import json
    contacts = result.get("contacts", [])
    status_text = result.get("status", "")
    # Save vendor signals OR client category
    vs = result.get("vendor_signals", {})
    cat = result.get("client_category", "")
    cat_conf = result.get("client_confidence", 0)
    if vs:
        jd.vendor_signals = json.dumps(vs)
    if cat:
        # Always store category (even for vendor mode, append to signals)
        existing = json.loads(jd.vendor_signals) if jd.vendor_signals else {}
        existing["category"] = cat
        existing["confidence"] = cat_conf
        jd.vendor_signals = json.dumps(existing)
    if not contacts:
        jd.status = "failed" if ("reach" in status_text or "skip" in status_text or "error" in status_text) else "no_email"
        jd.error = status_text if jd.status == "failed" else ""
        db.commit()
        return
    # keep only valid, deduped, best-first, up to the per-site limit
    valid = [c for c in contacts if valid_email(clean_email(c["email"]))]
    kept = 0
    for c in valid[:limit]:
        email = clean_email(c["email"])
        if db.query(ScraperResult).filter(ScraperResult.job_id == job.id,
                                          ScraperResult.email == email).first():
            continue
        db.add(ScraperResult(job_id=job.id, domain=jd.domain, email=email,
                             source_url=c.get("source_url", ""),
                             email_type=c.get("email_type", "domain_email"),
                             confidence=c.get("confidence", "medium")))
        kept += 1
    jd.status = "completed" if kept else "no_email"
    jd.source_url = valid[0].get("source_url", "") if valid else ""
    db.commit()


def _scrape_with_retry(domain: str, mode: str = "vendor") -> dict:
    """Try scraping, retry once on failure."""
    for attempt in range(2):
        try:
            result = scraper.extract_domain(domain, mode=mode)
            if "not reachable" in result.get("status", "") and attempt == 0:
                continue
            return result
        except Exception as e:
            if attempt == 0:
                continue
            return {"contacts": [], "status": f"error: {type(e).__name__}", "vendor_signals": {}}
    return {"contacts": [], "status": "error: max retries", "vendor_signals": {}}


CHUNK_SIZE = 100  # grab more at once since pool handles them continuously


MAX_RETRIES = 3


def _run(job_id: int):
    """Streaming worker with INTERLEAVED retry.
    Failed/no_email domains go back to END of queue immediately.
    Retry happens DURING the campaign, not after."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from collections import deque
    db = SessionLocal()
    try:
        job = db.get(ScraperJob, job_id)
        if not job: return
        _stop_flags.pop(job_id, None)  # fresh run — clear any old stop flag
        job.status = "running"; db.commit()
        limit = job.max_per_domain or 2
        mode = job.mode or "vendor"

        # Total domains in this job (for worker sizing + retry policy)
        total_domains = db.query(ScraperJobDomain).filter(
            ScraperJobDomain.job_id == job_id).count()
        # Retry ROUNDS that run AFTER the main pass finishes (big jobs get fewer)
        max_retry_rounds = 1 if total_domains > 1000 else 2

        workers = _effective_workers(total_domains)
        print(f"[WarmWire] Job #{job_id}: {total_domains} domains → {workers} workers")
        pool = ThreadPoolExecutor(max_workers=workers)

        def _refresh_counters():
            """Update done / emails_found. 'done' now only ever moves FORWARD,
            because failed domains are no longer pushed back to 'pending'
            mid-run (that made the progress bar stall / go backwards)."""
            try:
                job.done = (db.query(ScraperJobDomain)
                            .filter(ScraperJobDomain.job_id == job_id,
                                    ScraperJobDomain.status.in_(["completed", "failed", "no_email"]))
                            .count())
                job.emails_found = db.query(ScraperResult).filter(
                    ScraperResult.job_id == job_id).count()
                job.updated_at = datetime.utcnow()
                db.commit()
            except Exception:
                pass

        stopped = False

        # ROUND 0 = main pass over every pending domain.
        # ROUND 1+ = retry the ones that errored, only AFTER the main pass is done.
        for round_no in range(0, max_retry_rounds + 1):
            if stopped:
                break
            if round_no == 0:
                ids = [r[0] for r in db.query(ScraperJobDomain.id).filter(
                    ScraperJobDomain.job_id == job_id,
                    ScraperJobDomain.status == "pending").all()]
                label = "main pass"
            else:
                # Only retry real ERRORS. "no_email" means we checked fine and
                # the site simply has no address — re-scraping rarely helps and
                # would double the work on big lists.
                ids = [r[0] for r in db.query(ScraperJobDomain.id).filter(
                    ScraperJobDomain.job_id == job_id,
                    ScraperJobDomain.status == "failed").all()]
                label = f"retry round {round_no}"
            if not ids:
                continue
            print(f"[WarmWire] Job #{job_id}: {label} — {len(ids)} domains")

            pending_ids = deque(ids)
            futures = {}

            def _submit_next():
                while pending_ids:
                    did = pending_ids.popleft()
                    jd = db.get(ScraperJobDomain, did)
                    if not jd:
                        continue
                    jd.status = "scraping"; jd.last_checked = datetime.utcnow()
                    db.commit()
                    fut = pool.submit(_scrape_with_retry, jd.domain, mode)
                    futures[fut] = did
                    return True
                return False

            for _ in range(min(workers, len(pending_ids))):
                _submit_next()

            completed_since_update = 0
            update_every = 10 if len(ids) > 500 else 3

            while futures:
                done_fut = next(iter(as_completed(futures)))
                did = futures.pop(done_fut)

                # INSTANT STOP: checked on every single domain.
                if _stop_flags.get(job_id):
                    pool.shutdown(wait=False, cancel_futures=True)
                    db.refresh(job)
                    job.status = "stopped"; db.commit()
                    stopped = True
                    break

                try:
                    jd = db.get(ScraperJobDomain, did)
                    if jd:
                        try:
                            result = done_fut.result()
                        except Exception:
                            result = {"contacts": [], "status": "error", "vendor_signals": {}}
                        _save_result(db, job, jd, result, limit)
                        db.commit()  # commit so emails appear immediately
                        # NOTE: failed domains are deliberately NOT requeued here.
                        # They're handled in a retry round after the main pass.
                except Exception:
                    pass

                completed_since_update += 1
                if completed_since_update >= update_every:
                    try:
                        db.refresh(job)
                        if job.status == "stopped":
                            pool.shutdown(wait=False, cancel_futures=True)
                            stopped = True
                            break
                        _refresh_counters()
                    except Exception:
                        pass
                    completed_since_update = 0

                _submit_next()

            _refresh_counters()

        db.refresh(job)
        if job.status != "stopped":
            # Clean up: any domains still "pending" or "scraping" → mark as no_email
            db.query(ScraperJobDomain).filter(
                ScraperJobDomain.job_id == job_id,
                ScraperJobDomain.status.in_(["pending","scraping"])
            ).update({"status": "no_email"}, synchronize_session=False)
            job.done = db.query(ScraperJobDomain).filter(
                ScraperJobDomain.job_id == job_id,
                ScraperJobDomain.status.in_(["completed","failed","no_email"])).count()
            job.emails_found = db.query(ScraperResult).filter(ScraperResult.job_id == job_id).count()
            job.status = "completed"; job.updated_at = datetime.utcnow(); db.commit()
        pool.shutdown(wait=False)
    except Exception:
        try:
            job = db.get(ScraperJob, job_id)
            if job: job.status = "completed"; db.commit()
        except: pass
    finally:
        db.close()
        _threads.pop(job_id, None)
        _start_next_queued(job_id)


def _start_next_queued(finished_job_id: int = 0):
    """Start the next job waiting in the queue. Jobs run ONE AT A TIME so a big
    scrape can't saturate the machine and make the dashboard unresponsive."""
    try:
        # Someone still running? Then don't start another.
        if any(t.is_alive() for jid, t in _threads.items() if jid != finished_job_id):
            return
        s = SessionLocal()
        try:
            nxt = (s.query(ScraperJob)
                   .filter(ScraperJob.status == "queued")
                   .order_by(ScraperJob.id).first())
            if nxt:
                print(f"[WarmWire] Starting queued job #{nxt.id} ({nxt.name})")
                start(nxt.id)
        finally:
            s.close()
    except Exception as e:
        print(f"[WarmWire] Could not start next queued job: {e}")


def start(job_id: int):
    if job_id in _threads and _threads[job_id].is_alive():
        return
    t = threading.Thread(target=_run, args=(job_id,), daemon=True)
    _threads[job_id] = t
    t.start()


# ---------------- controls ----------------

def stop(db, job_id: int):
    # Set the in-memory flag FIRST so the worker halts on its next domain,
    # then mark the DB status. This makes Stop feel instant.
    _stop_flags[job_id] = True
    job = db.get(ScraperJob, job_id)
    if job and job.status == "running":
        job.status = "stopped"; db.commit()
    return job


def resume(db, job_id: int):
    """Resume a job. Works for stopped/queued jobs AND for orphaned jobs whose
    DB status still says "running" because the PC/server died mid-run (the
    thread is gone but the status was never updated)."""
    _stop_flags.pop(job_id, None)  # clear any stale stop flag
    job = db.get(ScraperJob, job_id)
    if not job:
        return None

    # Already genuinely running with a live thread? Nothing to do.
    t = _threads.get(job_id)
    if t is not None and t.is_alive():
        return job

    # Requeue any domains that were mid-scrape when the job died, otherwise
    # they'd be stuck in "scraping" forever and silently skipped.
    db.query(ScraperJobDomain).filter(
        ScraperJobDomain.job_id == job_id,
        ScraperJobDomain.status == "scraping"
    ).update({"status": "pending"}, synchronize_session=False)

    job.status = "running"
    db.commit()
    start(job_id)
    return job


def restart(db, job_id: int):
    _stop_flags.pop(job_id, None)  # clear any stale stop flag
    job = db.get(ScraperJob, job_id)
    if not job:
        return None
    db.query(ScraperResult).filter(ScraperResult.job_id == job_id).delete()
    for jd in db.query(ScraperJobDomain).filter(ScraperJobDomain.job_id == job_id).all():
        jd.status = "pending"; jd.error = ""; jd.source_url = ""; jd.last_checked = None
    job.done = 0; job.emails_found = 0; job.status = "running"; db.commit()
    start(job_id)
    return job


def retry_failed(db, job_id: int):
    """Re-queue all 'no_email' and 'failed' domains for another attempt.
    Keeps already-found emails intact. Only retries domains that had no result."""
    job = db.get(ScraperJob, job_id)
    if not job:
        return None
    _stop_flags.pop(job_id, None)  # clear stale stop flag before retrying
    retried = 0
    for jd in db.query(ScraperJobDomain).filter(
        ScraperJobDomain.job_id == job_id,
        ScraperJobDomain.status.in_(["no_email", "failed"])
    ).all():
        jd.status = "pending"
        jd.error = ""
        jd.last_checked = None
        retried += 1
    if retried:
        job.status = "running"
        job.done = job.done - retried  # adjust counter
        if job.done < 0: job.done = 0
        db.commit()
        start(job_id)
    return {"job_id": job_id, "retried": retried}


# ---------------- exports ----------------

def export_rows(db, job_id: int):
    rows = (db.query(ScraperResult)
            .filter(ScraperResult.job_id == job_id)
            .order_by(ScraperResult.domain).all())
    return [("Domain", "Email", "Email Type", "Confidence", "Source URL")] + \
           [(r.domain, r.email, r.email_type, r.confidence, r.source_url) for r in rows]


def export_csv(db, job_id: int) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in export_rows(db, job_id):
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def export_xlsx(db, job_id: int) -> bytes:
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Emails"
    for row in export_rows(db, job_id):
        ws.append(list(row))
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()
