"""Email Scraper API — mode-scoped jobs, live status, controls, exports.

Mode (vendor/client) is the isolation key so the two dashboards never see each
other's jobs. (When the login system is wired, add a user_id alongside mode.)
"""
import asyncio as _asyncio
import sqlite3 as _sqlite3
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .config import settings as _settings
from .crm_models import ScraperJob, ScraperJobDomain, ScraperResult
from . import scraper_jobs

router = APIRouter(prefix="/crm/scraper", tags=["scraper"])


def _owned(db: Session, job_id: int, mode: str) -> ScraperJob:
    job = db.get(ScraperJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if mode and job.mode != mode:
        raise HTTPException(403, "This job belongs to another dashboard.")
    return job


class SplitIn(BaseModel):
    mode: str = "vendor"
    batch_size: int = 5000


@router.post("/outreach/dedupe")
def dedupe_outreach(mode: str = "vendor", dry_run: bool = True,
                    db: Session = Depends(get_db)):
    """Remove duplicate rows from a mode's outreach list, keeping ONE per email.

    Earlier builds added scraped emails before the email-level duplicate check
    existed, so the same address can appear several times. This keeps the
    earliest row for each email (its status/history) and deletes the rest.
    dry_run=True (default) only reports what WOULD be removed — nothing is
    deleted until you call it again with dry_run=false.
    """
    from .crm_models import OutreachEntry
    rows = db.query(OutreachEntry.id, OutreachEntry.email).filter(
        OutreachEntry.mode == mode).order_by(OutreachEntry.id.asc()).all()

    seen = set()
    dup_ids = []
    for rid, email in rows:
        key = (email or "").strip().lower()
        if not key:
            continue
        if key in seen:
            dup_ids.append(rid)      # a later copy of an email we already kept
        else:
            seen.add(key)

    result = {"mode": mode, "total_rows": len(rows),
              "unique_emails": len(seen), "duplicates": len(dup_ids),
              "dry_run": dry_run}

    if dry_run or not dup_ids:
        result["message"] = (f"{len(dup_ids)} duplicate row(s) would be removed, "
                             f"leaving {len(seen)} unique."
                             if dup_ids else "No duplicates found.")
        return result

    # Delete in chunks so we never hold a huge write lock (the scraper may be
    # running at the same time).
    removed = 0
    CHUNK = 500
    for i in range(0, len(dup_ids), CHUNK):
        batch = dup_ids[i:i + CHUNK]
        db.query(OutreachEntry).filter(OutreachEntry.id.in_(batch)).delete(
            synchronize_session=False)
        db.commit()
        removed += len(batch)

    result["removed"] = removed
    result["message"] = f"Removed {removed} duplicate row(s). {len(seen)} unique remain."
    return result


@router.post("/jobs/{job_id}/split")
def split_job(job_id: int, data: SplitIn, db: Session = Depends(get_db)):
    """Break one oversized job's PENDING domains into several smaller queued
    jobs of `batch_size` each. They run one at a time (existing queue behaviour),
    so a 17k-domain list becomes e.g. 4 x 5000 that chain automatically and keep
    the machine responsive. Already-scraped domains in the original job are left
    as they are; only the not-yet-done ones are moved into batches.
    """
    job = _owned(db, job_id, data.mode)
    size = max(500, min(int(data.batch_size or 5000), 8000))

    # Stop the original if it's still marked running/queued, and pull its
    # unfinished domains.
    if job.status in ("running", "queued", "preparing"):
        scraper_jobs._stop_flags[job_id] = True
        job.status = "stopped"
        db.commit()

    pend = (db.query(ScraperJobDomain)
            .filter(ScraperJobDomain.job_id == job_id,
                    ScraperJobDomain.status.in_(["pending", "scraping"]))
            .all())
    domains = [d.domain for d in pend]
    if not domains:
        return {"batches": 0, "message": "No pending domains left to batch.",
                "moved": 0}

    # De-dupe defensively while preserving order.
    seen = set(); uniq = []
    for d in domains:
        if d and d not in seen:
            seen.add(d); uniq.append(d)

    batches = []
    n = 0
    for i in range(0, len(uniq), size):
        chunk = uniq[i:i + size]
        n += 1
        child = scraper_jobs.create_job_shell(
            db, job.mode, f"{job.name or 'Batch'} — part {n}",
            source="split", max_per_domain=job.max_per_domain or 2)
        scraper_jobs._fill_domains(db, child, chunk)
        child.status = "queued"
        db.commit()
        batches.append({"job_id": child.id, "name": child.name, "count": len(chunk)})

    # Remove the moved pending rows from the original so its counts read true.
    db.query(ScraperJobDomain).filter(
        ScraperJobDomain.job_id == job_id,
        ScraperJobDomain.status.in_(["pending", "scraping"])
    ).delete(synchronize_session=False)
    # The original now reflects only what it actually finished.
    job.total = db.query(ScraperJobDomain).filter(
        ScraperJobDomain.job_id == job_id).count()
    job.done = job.total
    if job.status != "stopped":
        job.status = "completed"
    db.commit()

    # Kick off the first batch; the rest follow automatically as each finishes.
    scraper_jobs._start_next_queued()

    return {"batches": n, "batch_size": size, "moved": len(uniq),
            "jobs": batches,
            "message": f"Split into {n} batch(es) of up to {size}. "
                       f"They will run one after another automatically."}


class JobIn(BaseModel):
    mode: str = "vendor"
    name: str = ""
    domains: list[str] = []
    sheet_csv_url: str = ""   # optional: a Google Sheet published as CSV
    max_per_domain: int = 2   # keep best N emails per site (1-10)


@router.post("/jobs")
def create_job(data: JobIn, db: Session = Depends(get_db)):
    """Returns as soon as the job row exists. Fetching the sheet and inserting
    the domains happens in the background — the panel polls for progress."""
    if not data.domains and not data.sheet_csv_url.strip():
        raise HTTPException(400, "No domains provided.")
    source = "sheet" if data.sheet_csv_url.strip() else "manual"
    job = scraper_jobs.create_job_shell(db, data.mode, data.name, source,
                                        data.max_per_domain)
    scraper_jobs.prepare_and_start(job.id, list(data.domains),
                                   data.sheet_csv_url.strip())
    return {"job_id": job.id, "total": 0, "status": "preparing", "mode": job.mode}


@router.get("/jobs")
def list_jobs(mode: str = "", db: Session = Depends(get_db)):
    q = db.query(ScraperJob)
    if mode:
        q = q.filter(ScraperJob.mode == mode)
    return [{"id": j.id, "name": j.name, "mode": j.mode, "status": j.status,
             "total": j.total, "done": j.done, "emails_found": j.emails_found,
             "created_at": j.created_at.isoformat()} for j in q.order_by(ScraperJob.id.desc()).all()]


@router.get("/jobs/{job_id}")
@router.get("/jobs/{job_id}/live")
async def job_live(job_id: int, dom_limit: int = 60, email_limit: int = 60):
    """Light live lists (recent domains + emails) on a read-only connection, so
    the panel's tables keep filling even while a big scrape hammers the DB.
    The heavy /jobs/{id} stays for the full snapshot; this is what the poll uses
    for the live view so it never comes back empty behind the scrape's writes."""
    dom_limit = max(1, min(int(dom_limit or 60), 300))
    email_limit = max(1, min(int(email_limit or 60), 300))

    def _read():
        path = _settings.DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", "")
        con = _sqlite3.connect(path, timeout=4)
        try:
            con.execute("PRAGMA query_only=ON")
            job = con.execute("SELECT status, done, total, emails_found FROM scraper_jobs WHERE id=?",
                              (job_id,)).fetchone()
            if not job:
                return None
            # per-status counts for the whole job
            counts = {}
            for st, cnt in con.execute(
                "SELECT status, count(*) FROM scraper_job_domains WHERE job_id=? GROUP BY status",
                    (job_id,)).fetchall():
                counts[st or "pending"] = cnt
            dom_total = con.execute("SELECT count(*) FROM scraper_job_domains WHERE job_id=?",
                                    (job_id,)).fetchone()[0]
            doms = con.execute(
                "SELECT domain, status, error, source_url, is_duplicate, vendor_signals, last_checked "
                "FROM scraper_job_domains WHERE job_id=? "
                "ORDER BY last_checked DESC, id DESC LIMIT ?", (job_id, dom_limit)).fetchall()
            em_total = con.execute("SELECT count(*) FROM scraper_results WHERE job_id=?",
                                   (job_id,)).fetchone()[0]
            ems = con.execute(
                "SELECT domain, email, source_url, email_type, confidence "
                "FROM scraper_results WHERE job_id=? ORDER BY id DESC LIMIT ?",
                (job_id, email_limit)).fetchall()
            return {
                "id": job_id, "status": job[0], "done": job[1], "total": job[2],
                "emails_found": job[3],
                "progress": round(job[1] / job[2] * 100, 1) if job[2] else 0,
                "domains_total": dom_total, "emails_total": em_total,
                "status_counts": counts,
                "domains": [{"domain": d[0], "status": d[1], "error": d[2],
                             "source_url": d[3], "is_duplicate": bool(d[4]),
                             "vendor_signals": d[5], "last_checked": d[6]} for d in doms],
                "emails": [{"domain": e[0], "email": e[1], "source_url": e[2],
                            "email_type": e[3], "confidence": e[4]} for e in ems],
            }
        finally:
            con.close()
    data = await _asyncio.to_thread(_read)
    if data is None:
        raise HTTPException(404, "Job not found")
    return data


@router.get("/jobs/{job_id}/progress")
async def job_progress(job_id: int):
    """Ultra-light live counter, safe to poll every second even mid-scrape.

    The full /jobs/{id} endpoint runs several ORM queries on a pooled
    connection; while a big scrape hammers the same SQLite file, those can
    queue behind the scrape's writes and the UI looks frozen. This one is
    async (so it runs on the event loop, not the request threadpool), opens
    its own short read-only connection in WAL read mode, and does a single
    cheap SELECT. It returns just enough for the header counters to keep
    moving so the panel always feels alive."""
    def _read():
        path = _settings.DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", "")
        con = _sqlite3.connect(path, timeout=3)
        try:
            con.execute("PRAGMA query_only=ON")
            row = con.execute(
                "SELECT status, done, total, emails_found FROM scraper_jobs WHERE id=?",
                (job_id,)).fetchone()
            if not row:
                return None
            sc = con.execute(
                "SELECT count(*) FROM scraper_job_domains WHERE job_id=? AND status='scraping'",
                (job_id,)).fetchone()[0]
            return {"id": job_id, "status": row[0], "done": row[1],
                    "total": row[2], "emails_found": row[3], "scraping": sc,
                    "progress": round(row[1] / row[2] * 100, 1) if row[2] else 0}
        finally:
            con.close()
    # Run the blocking sqlite read in a thread so we never block the loop.
    data = await _asyncio.to_thread(_read)
    if data is None:
        raise HTTPException(404, "Job not found")
    return data


@router.get("/running")
async def running_job(mode: str = "vendor"):
    """Which scrape is live right now (most recent running job for this mode).
    Lets the panel auto-attach to a job started elsewhere (e.g. a batch) so the
    user always sees the live one without hunting through Previous jobs."""
    def _read():
        path = _settings.DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", "")
        con = _sqlite3.connect(path, timeout=3)
        try:
            con.execute("PRAGMA query_only=ON")
            row = con.execute(
                "SELECT id, name, done, total, emails_found FROM scraper_jobs "
                "WHERE status='running' AND mode=? ORDER BY id DESC LIMIT 1",
                (mode,)).fetchone()
            if row:
                return {"id": row[0], "name": row[1], "done": row[2],
                        "total": row[3], "emails_found": row[4]}
            # none running — offer the most recent queued one so the UI can show
            # "waiting" instead of nothing
            row = con.execute(
                "SELECT id, name, done, total, emails_found FROM scraper_jobs "
                "WHERE status='queued' AND mode=? ORDER BY id ASC LIMIT 1",
                (mode,)).fetchone()
            if row:
                return {"id": row[0], "name": row[1], "done": row[2],
                        "total": row[3], "emails_found": row[4], "queued": True}
            return {"id": None}
        finally:
            con.close()
    return await _asyncio.to_thread(_read)


def job_status(job_id: int, mode: str = "", dom_limit: int = 300,
               email_limit: int = 300, db: Session = Depends(get_db)):
    """Live snapshot for polling: progress + a WINDOW of domains/emails.

    This used to return every domain and every email on every poll. On a
    4,000-domain job that's a ~2 MB response every 1.5 seconds, which the
    browser then re-rendered into 4,000 DOM rows — the tab could not finish
    one poll before the next fired, so the whole dashboard locked up and new
    requests appeared to hang. We now send only what's actually on screen;
    the totals and the per-status counts still describe the whole job, and
    the export endpoints still return everything.
    """
    job = _owned(db, job_id, mode)

    dom_limit = max(1, min(int(dom_limit or 300), 2000))
    email_limit = max(1, min(int(email_limit or 300), 2000))

    base = db.query(ScraperJobDomain).filter(ScraperJobDomain.job_id == job_id)
    domains_total = base.count()

    # Full-job breakdown, one cheap GROUP BY instead of shipping every row.
    status_counts = {}
    for st, cnt in (db.query(ScraperJobDomain.status, func.count(ScraperJobDomain.id))
                    .filter(ScraperJobDomain.job_id == job_id)
                    .group_by(ScraperJobDomain.status).all()):
        status_counts[st or "pending"] = cnt

    # Most recently touched first — that's the live edge of the run, which is
    # the part worth watching. Untouched (pending) rows sort last.
    domains = (base.order_by(ScraperJobDomain.last_checked.desc().nullslast(),
                             ScraperJobDomain.id.desc())
               .limit(dom_limit).all())

    res_base = db.query(ScraperResult).filter(ScraperResult.job_id == job_id)
    emails_total = res_base.count()
    results = res_base.order_by(ScraperResult.id.desc()).limit(email_limit).all()

    return {
        "id": job.id, "name": job.name, "mode": job.mode, "status": job.status,
        "total": job.total, "done": job.done, "emails_found": job.emails_found,
        "progress": round(job.done / job.total * 100, 1) if job.total else 0,
        "workers": scraper_jobs._effective_workers(job.total) if job.total else 20,
        # Totals for the whole job, so the UI can say "showing 300 of 4338".
        "domains_total": domains_total,
        "emails_total": emails_total,
        "status_counts": status_counts,
        "error": scraper_jobs._prepare_errors.get(job_id, ""),
        "domains": [{"domain": d.domain, "status": d.status, "error": d.error,
                     "source_url": d.source_url, "is_duplicate": d.is_duplicate,
                     "vendor_signals": d.vendor_signals,
                     "last_checked": d.last_checked.isoformat() if d.last_checked else None}
                    for d in domains],
        "emails": [{"domain": r.domain, "email": r.email, "source_url": r.source_url,
                   "email_type": r.email_type, "confidence": r.confidence}
                  for r in results],
    }


@router.post("/jobs/{job_id}/stop")
def stop_job(job_id: int, mode: str = "", db: Session = Depends(get_db)):
    _owned(db, job_id, mode)
    j = scraper_jobs.stop(db, job_id)
    return {"status": j.status}


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: int, mode: str = "", db: Session = Depends(get_db)):
    _owned(db, job_id, mode)
    j = scraper_jobs.resume(db, job_id)
    return {"status": j.status}


@router.post("/jobs/{job_id}/restart")
def restart_job(job_id: int, mode: str = "", db: Session = Depends(get_db)):
    _owned(db, job_id, mode)
    j = scraper_jobs.restart(db, job_id)
    return {"status": j.status}


@router.post("/jobs/{job_id}/retry-failed")
def retry_failed_job(job_id: int, mode: str = "", db: Session = Depends(get_db)):
    """Re-try all no_email and failed domains. Keeps existing found emails."""
    _owned(db, job_id, mode)
    result = scraper_jobs.retry_failed(db, job_id)
    return result or {"error": "not found"}


@router.get("/jobs/{job_id}/export")
def export_job(job_id: int, format: str = "csv", mode: str = "", db: Session = Depends(get_db)):
    _owned(db, job_id, mode)
    if format == "xlsx":
        data = scraper_jobs.export_xlsx(db, job_id)
        return Response(content=data,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="scraper_{job_id}.xlsx"'})
    data = scraper_jobs.export_csv(db, job_id)
    return Response(content=data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="scraper_{job_id}.csv"'})
