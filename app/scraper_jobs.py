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
TOTAL_WORKER_BUDGET = 60


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


# Free / hosted-subdomain providers. A site on one of these (e.g.
# myblog.blogspot.com) is a free page, not a real business — reject the whole
# domain everywhere so no time is wasted scraping it.
FREE_HOST_SUFFIXES = (
    "blogspot.com", "wordpress.com", "wixsite.com", "wix.com", "weebly.com",
    "squarespace.com", "webflow.io", "wordpress.org", "blogger.com",
    "tumblr.com", "medium.com", "substack.com", "ghost.io", "over-blog.com",
    "livejournal.com", "typepad.com", "jimdo.com", "jimdofree.com",
    "godaddysites.com", "site123.me", "yolasite.com", "webnode.com",
    "webs.com", "strikingly.com", "carrd.co", "notion.site", "framer.website",
    "framer.app", "netlify.app", "netlify.com", "vercel.app", "herokuapp.com",
    "github.io", "gitlab.io", "pages.dev", "web.app", "firebaseapp.com",
    "myshopify.com", "bigcartel.com", "storenvy.com", "ecwid.com",
    "wixstudio.com", "mystrikingly.com", "glitch.me", "repl.co",
    "surge.sh", "000webhostapp.com", "wpcomstaging.com", "hashnode.dev",
    "gumroad.com", "carbonmade.com", "journoportfolio.com", "contently.com",
    "wordpress.blog", "home.blog", "blog.com", "weebly.site",
)


def is_free_host(domain: str) -> bool:
    """True if the domain is on a free/hosted-subdomain provider (blogspot,
    wordpress.com, wix, etc). These are rejected by every scraper."""
    d = (domain or "").strip().lower().replace("www.", "")
    if not d:
        return True
    return any(d == suf or d.endswith("." + suf) for suf in FREE_HOST_SUFFIXES)


def normalize_domain(raw: str) -> str:
    d = raw.strip().lower()
    if not d:
        return ""
    if "//" not in d:
        d = "https://" + d
    host = urlparse(d).netloc or urlparse(d).path
    host = host.replace("www.", "").split("/")[0].strip()
    # Reject free-host domains outright — they never make good business leads.
    if is_free_host(host):
        return ""
    return host


def clean_email(e: str) -> str:
    return (e or "").strip().strip(".,;:<>()[]\"'").lower()


def valid_email(e: str) -> bool:
    return bool(EMAIL_RE.match(e)) and not e.endswith(JUNK_ENDINGS)


# ---------------- job creation ----------------

# Why a job failed while it was still being prepared (no column on the model,
# and it only matters until the page is refreshed).
_prepare_errors: dict[int, str] = {}


def create_job_shell(db, mode: str, name: str, source: str = "manual",
                     max_per_domain: int = 2) -> ScraperJob:
    """One tiny INSERT, nothing else — so the HTTP request can return at once."""
    job = ScraperJob(mode=mode, name=name or f"Scrape {datetime.utcnow():%H:%M}",
                     source=source, status="preparing", total=0,
                     max_per_domain=max(1, min(int(max_per_domain or 2), 10)))
    db.add(job); db.commit(); db.refresh(job)
    return job


def prepare_and_start(job_id: int, domains: list[str], sheet_csv_url: str = ""):
    """Do the slow part off the request thread.

    Downloading the sheet and inserting a few thousand rows used to happen
    inside POST /crm/scraper/jobs, so the browser sat on 'Starting…' until all
    of it finished. requests' timeout is per socket read, not a total budget —
    a sheet that trickles in can hold the request open for minutes. Now the
    request returns a job id immediately and the panel polls for the rest.
    """
    t = threading.Thread(target=_prepare, args=(job_id, list(domains), sheet_csv_url),
                         daemon=True)
    t.start()


def _fail_prepare(db, job, msg: str):
    print(f"[WarmWire] Job #{job.id} could not be prepared: {msg}")
    _prepare_errors[job.id] = msg
    job.status = "error"
    db.commit()


def _prepare(job_id: int, domains: list[str], sheet_csv_url: str = ""):
    db = SessionLocal()
    try:
        job = db.get(ScraperJob, job_id)
        if not job:
            return
        all_domains = list(domains)

        if sheet_csv_url:
            try:
                import requests, csv, io, re as _re
                r = requests.get(sheet_csv_url, timeout=(10, 30),
                                 headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                txt = r.text
                ctype = r.headers.get("content-type", "").lower()
                # Guard: a sheet that isn't published-to-web returns an HTML login
                # or error page, not CSV. Detect that instead of treating the
                # error text as a "domain" (which then crashed the scrape).
                looks_html = ("<html" in txt[:500].lower()
                              or "<!doctype" in txt[:500].lower())
                if looks_html or ("csv" not in ctype and "text/plain" not in ctype
                                  and "," not in txt[:200] and "\n" not in txt[:200]):
                    _fail_prepare(db, job,
                        "That link didn't return CSV. In Google Sheets use "
                        "File → Share → Publish to web → CSV, and paste that link "
                        "(it ends with output=csv).")
                    return
                # Extract only things that actually look like domains.
                dom_re = _re.compile(
                    r"^(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9\-]*\.[a-z0-9\-.]+)",
                    _re.I)
                for row in csv.reader(io.StringIO(txt)):
                    for cell in row:
                        cell = (cell or "").strip()
                        if not cell or "@" in cell or " " in cell:
                            continue
                        m = dom_re.match(cell)
                        if m:
                            all_domains.append(m.group(1).lower())
            except Exception as e:
                _fail_prepare(db, job, f"Could not read the sheet CSV ({type(e).__name__}). "
                                       f"Make sure it's published to the web as CSV.")
                return

        if not all_domains:
            _fail_prepare(db, job, "No domains found.")
            return

        _fill_domains(db, job, all_domains)
        _prepare_errors.pop(job_id, None)
        job.status = "queued"
        db.commit()
        start(job_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        try:
            job = db.get(ScraperJob, job_id)
            if job:
                _fail_prepare(db, job, f"{type(e).__name__}: {e}")
        except Exception:
            pass
    finally:
        db.close()


def _fill_domains(db, job: ScraperJob, domains: list[str]) -> int:
    """Normalise, dedupe against history, and insert the job's domain rows."""
    seen, clean_domains = set(), []
    for raw in domains:
        d = normalize_domain(raw)
        if d and d not in seen:
            seen.add(d)
            clean_domains.append(d)

    # Which domains have we already scraped in this mode? Fetch them ONCE.
    # This used to run a JOIN query per domain — with a few thousand domains
    # that's a few thousand queries inside the HTTP request, which is why
    # creating a big job appeared to hang on "Starting...".
    already = set()
    try:
        rows = (db.query(ScraperJobDomain.domain)
                .join(ScraperJob, ScraperJob.id == ScraperJobDomain.job_id)
                .filter(ScraperJob.mode == job.mode,
                        ScraperJobDomain.status.in_(["completed", "no_email"]))
                .distinct().all())
        already = {r[0] for r in rows if r[0]}
    except Exception:
        already = set()

    # Insert in chunks so one huge transaction doesn't hold the write lock
    CHUNK = 500
    batch = []
    for d in clean_domains:
        batch.append(ScraperJobDomain(job_id=job.id, domain=d,
                                      is_duplicate=(d in already)))
        if len(batch) >= CHUNK:
            db.add_all(batch); db.commit(); batch = []
    if batch:
        db.add_all(batch)
    job.total = len(clean_domains)
    db.commit()
    print(f"[WarmWire] Job #{job.id} created with {len(clean_domains)} domain(s) "
          f"({len(already & set(clean_domains))} seen before)")
    return len(clean_domains)


def create_job(db, mode: str, name: str, domains: list[str], source: str = "manual",
               max_per_domain: int = 2) -> ScraperJob:
    """Synchronous creation — kept for scripts/tests. The API uses the
    shell + background prepare pair above so the browser never waits."""
    job = create_job_shell(db, mode, name, source, max_per_domain)
    _fill_domains(db, job, domains)
    job.status = "queued"
    db.commit()
    return job


# ---------------- the worker ----------------


def _scrape_one(domain: str, mode: str = "vendor") -> dict:
    """Network only — safe to run in a thread (no DB access here)."""
    try:
        return scraper.extract_domain(domain, mode=mode)
    except Exception as e:
        import traceback; traceback.print_exc()
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
        # Prefer the specific error (e.g. "DNS: domain does not resolve") over the
        # generic status, so retry rounds can skip DNS-dead hosts.
        specific = result.get("error", "")
        jd.error = (specific or status_text) if jd.status == "failed" else ""
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


# One domain's absolute ceiling. Enforced INSIDE extract_domain via the shared
# session's per-request timeouts plus its own DOMAIN_BUDGET check between pages.
# (An earlier version ran each domain in a throwaway thread and abandoned it on
# timeout — but the abandoned thread kept holding a connection from the shared
# HTTP session's pool, which leaked connections until healthy sites started
# failing to connect and got mis-marked "no_email". The timeout belongs on the
# socket, not on a wrapper thread.)


def _scrape_with_retry(domain: str, mode: str = "vendor") -> dict:
    """Try scraping, retry once on failure. The per-page socket timeouts and
    extract_domain's own budget keep any single domain bounded."""
    for attempt in range(2):
        try:
            result = scraper.extract_domain(domain, mode=mode)
            status = result.get("status", "")
            if ("not reachable" in status or "timed out" in status) and attempt == 0:
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
    from concurrent.futures import (ThreadPoolExecutor, as_completed,
                                wait as futures_wait, FIRST_COMPLETED)
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

        # How many changes to hold before writing them out together
        COMMIT_EVERY = 25
        uncommitted = 0

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
                # Skip DNS-dead hosts entirely: if the domain doesn't resolve,
                # a second attempt will fail identically, so retrying them just
                # doubles the time on a list full of dead domains.
                ids = [r[0] for r in db.query(ScraperJobDomain.id).filter(
                    ScraperJobDomain.job_id == job_id,
                    ScraperJobDomain.status == "failed",
                    ~ScraperJobDomain.error.like("DNS:%")).all()]
                label = f"retry round {round_no}"
            if not ids:
                continue
            print(f"[WarmWire] Job #{job_id}: {label} — {len(ids)} domains")

            pending_ids = deque(ids)
            futures = {}

            def _submit_next():
                # `uncommitted` is the outer counter, not a fresh local — without
                # this the very first call raised UnboundLocalError and the whole
                # job died before scraping a single domain.
                nonlocal uncommitted
                while pending_ids:
                    did = pending_ids.popleft()
                    jd = db.get(ScraperJobDomain, did)
                    if not jd:
                        continue
                    jd.status = "scraping"; jd.last_checked = datetime.utcnow()
                    uncommitted += 1
                    if uncommitted >= COMMIT_EVERY:
                        db.commit()
                        uncommitted = 0
                    fut = pool.submit(_scrape_with_retry, jd.domain, mode)
                    futures[fut] = did
                    return True
                return False

            for _ in range(min(workers, len(pending_ids))):
                _submit_next()

            completed_since_update = 0
            update_every = 10 if len(ids) > 500 else 3

            while futures:
                # Wait for whichever workers have finished, then handle them all.
                #
                # This used to call as_completed() afresh for every single domain
                # and take only the first result. Each call registers a waiter on
                # EVERY outstanding future, so with fifty workers that was fifty
                # registrations per domain — the throughput collapsed as the job
                # grew. wait(FIRST_COMPLETED) is built for exactly this.
                # Short wait so Stop is felt almost instantly and a domain that
                # overruns its budget can't keep the loop parked for 30s. Most
                # iterations still return the moment a worker finishes; the
                # timeout is only the ceiling on how long we sit blocked.
                done_set, _pending = futures_wait(
                    list(futures.keys()), timeout=2,
                    return_when=FIRST_COMPLETED)

                if not done_set:
                    # Nothing finished in the short window. Check for Stop, then
                    # loop again. If a single domain's worker overran the whole
                    # domain budget (a pathological site), don't wait on it
                    # forever — drop that future, mark the domain timed out, and
                    # let a fresh domain take the slot so no worker sits idle.
                    if _stop_flags.get(job_id):
                        pool.shutdown(wait=False, cancel_futures=True)
                        db.refresh(job)
                        job.status = "stopped"; db.commit()
                        stopped = True
                        break
                    _slow_ticks = locals().get("_slow_ticks", 0) + 1
                    if _slow_ticks * 2 >= scraper.DOMAIN_BUDGET + 4 and futures:
                        # ~26s with zero completions → the whole batch of in-flight
                        # workers is wedged (typically all stuck in a slow connect
                        # phase at once). Release ALL of them, not just the oldest,
                        # mark their domains timed-out, and refill the pool so it
                        # can move on. Releasing one-at-a-time here left the other
                        # 48 workers stuck and the job frozen.
                        for stuck_fut in list(futures.keys()):
                            stuck_did = futures.pop(stuck_fut, None)
                            stuck_fut.cancel()
                            if stuck_did is not None:
                                try:
                                    jd = db.get(ScraperJobDomain, stuck_did)
                                    if jd and jd.status == "scraping":
                                        jd.status = "failed"
                                        jd.error = "timeout: no response"
                                except Exception:
                                    pass
                        try:
                            db.commit()
                        except Exception:
                            db.rollback()
                        _slow_ticks = 0
                        # Refill the pool with fresh domains
                        for _ in range(workers):
                            if not _submit_next():
                                break
                        continue
                    continue
                _slow_ticks = 0

                for done_fut in done_set:
                  did = futures.pop(done_fut, None)
                  if did is None:
                      continue

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
                        # Batched commit: writing after every single domain made
                        # every worker queue behind the SQLite write lock.
                        uncommitted += 1
                        if uncommitted >= COMMIT_EVERY:
                            db.commit()
                            uncommitted = 0
                        # NOTE: failed domains are deliberately NOT requeued here.
                        # They're handled in a retry round after the main pass.
                  except Exception:
                    pass

                  completed_since_update += 1
                  if completed_since_update >= update_every:
                    try:
                        if uncommitted:
                            db.commit()
                            uncommitted = 0
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

                if stopped:
                    break

            if uncommitted:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                uncommitted = 0
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
    except Exception as run_err:
        # Report it. Swallowing this silently made a crashed job look like a
        # finished one, which is how a broken run hid for so long.
        import traceback
        print(f"[WarmWire] Job #{job_id} crashed: {type(run_err).__name__}: {run_err}")
        traceback.print_exc()
        try:
            job = db.get(ScraperJob, job_id)
            if job:
                job.status = "error"
                db.commit()
        except Exception:
            pass
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
