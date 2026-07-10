"""Email-scraper job engine.

Wraps the compliant `scraper.extract_domain` (company's own public business pages,
same-domain published addresses only) as the core engine, and runs batches as
background jobs with live per-domain status, stop/resume/restart, dedup, email
validation, and CSV/XLSX export. Jobs are scoped by mode (vendor/client).
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

WORKERS = 20   # 20 domains parallel = super fast


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
    if vs:
        jd.vendor_signals = json.dumps(vs)
    elif cat:
        jd.vendor_signals = json.dumps({"category": cat})
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


CHUNK_SIZE = 50


def _run(job_id: int):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    db = SessionLocal()
    try:
        job = db.get(ScraperJob, job_id)
        if not job:
            return
        job.status = "running"; db.commit()
        limit = job.max_per_domain or 2
        mode = job.mode or "vendor"

        pool = ThreadPoolExecutor(max_workers=WORKERS)
        try:
            while True:
                db.refresh(job)
                if job.status == "stopped":
                    break

                chunk = (db.query(ScraperJobDomain)
                         .filter(ScraperJobDomain.job_id == job_id,
                                 ScraperJobDomain.status == "pending")
                         .limit(CHUNK_SIZE).all())
                if not chunk:
                    break

                for jd in chunk:
                    jd.status = "scraping"; jd.last_checked = datetime.utcnow()
                db.commit()

                futures = {pool.submit(_scrape_with_retry, jd.domain, mode): jd for jd in chunk}
                for fut in as_completed(futures):
                    try:
                        db.refresh(job)
                        if job.status == "stopped":
                            pool.shutdown(wait=False, cancel_futures=True)
                            break
                        jd = futures[fut]
                        try:
                            result = fut.result()
                        except Exception:
                            result = {"contacts": [], "status": "error: thread crash", "vendor_signals": {}}
                        _save_result(db, job, jd, result, limit)
                        # UPDATE COUNTERS AFTER EACH DOMAIN (not after chunk)
                        job.done = (db.query(ScraperJobDomain)
                                    .filter(ScraperJobDomain.job_id == job_id,
                                            ScraperJobDomain.status.in_(["completed", "failed", "no_email"]))
                                    .count())
                        job.emails_found = db.query(ScraperResult).filter(ScraperResult.job_id == job_id).count()
                        job.updated_at = datetime.utcnow(); db.commit()
                    except Exception:
                        pass

            db.refresh(job)
            if job.status != "stopped":
                job.status = "completed"; job.updated_at = datetime.utcnow(); db.commit()
        finally:
            pool.shutdown(wait=False)
    except Exception:
        try:
            job = db.get(ScraperJob, job_id)
            if job:
                job.status = "completed"; db.commit()
        except Exception:
            pass
    finally:
        db.close()
        _threads.pop(job_id, None)


def start(job_id: int):
    if job_id in _threads and _threads[job_id].is_alive():
        return
    t = threading.Thread(target=_run, args=(job_id,), daemon=True)
    _threads[job_id] = t
    t.start()


# ---------------- controls ----------------

def stop(db, job_id: int):
    job = db.get(ScraperJob, job_id)
    if job and job.status == "running":
        job.status = "stopped"; db.commit()
    return job


def resume(db, job_id: int):
    job = db.get(ScraperJob, job_id)
    if job and job.status in ("stopped", "queued"):
        job.status = "running"; db.commit()
        start(job_id)
    return job


def restart(db, job_id: int):
    job = db.get(ScraperJob, job_id)
    if not job:
        return None
    db.query(ScraperResult).filter(ScraperResult.job_id == job_id).delete()
    for jd in db.query(ScraperJobDomain).filter(ScraperJobDomain.job_id == job_id).all():
        jd.status = "pending"; jd.error = ""; jd.source_url = ""; jd.last_checked = None
    job.done = 0; job.emails_found = 0; job.status = "running"; db.commit()
    start(job_id)
    return job


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
