"""Email Scraper API — mode-scoped jobs, live status, controls, exports.

Mode (vendor/client) is the isolation key so the two dashboards never see each
other's jobs. (When the login system is wired, add a user_id alongside mode.)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
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


class JobIn(BaseModel):
    mode: str = "vendor"
    name: str = ""
    domains: list[str] = []
    sheet_csv_url: str = ""   # optional: a Google Sheet published as CSV
    max_per_domain: int = 2   # keep best N emails per site (1-10)


@router.post("/jobs")
def create_job(data: JobIn, db: Session = Depends(get_db)):
    domains = list(data.domains)
    source = "manual"
    if data.sheet_csv_url:
        source = "sheet"
        try:
            import requests, csv, io
            txt = requests.get(data.sheet_csv_url, timeout=20).text
            for row in csv.reader(io.StringIO(txt)):
                for cell in row:
                    if cell and "." in cell and "@" not in cell:
                        domains.append(cell)
        except Exception as e:
            raise HTTPException(400, f"Could not read the sheet CSV: {type(e).__name__}")
    if not domains:
        raise HTTPException(400, "No domains provided.")
    job = scraper_jobs.create_job(db, data.mode, data.name, domains, source, data.max_per_domain)
    scraper_jobs.start(job.id)
    return {"job_id": job.id, "total": job.total, "mode": job.mode}


@router.get("/jobs")
def list_jobs(mode: str = "", db: Session = Depends(get_db)):
    q = db.query(ScraperJob)
    if mode:
        q = q.filter(ScraperJob.mode == mode)
    return [{"id": j.id, "name": j.name, "mode": j.mode, "status": j.status,
             "total": j.total, "done": j.done, "emails_found": j.emails_found,
             "created_at": j.created_at.isoformat()} for j in q.order_by(ScraperJob.id.desc()).all()]


@router.get("/jobs/{job_id}")
def job_status(job_id: int, mode: str = "", db: Session = Depends(get_db)):
    """Live snapshot for polling: job progress + per-domain status + emails found."""
    job = _owned(db, job_id, mode)
    domains = db.query(ScraperJobDomain).filter(ScraperJobDomain.job_id == job_id).all()
    results = db.query(ScraperResult).filter(ScraperResult.job_id == job_id).all()
    return {
        "id": job.id, "name": job.name, "mode": job.mode, "status": job.status,
        "total": job.total, "done": job.done, "emails_found": job.emails_found,
        "progress": round(job.done / job.total * 100, 1) if job.total else 0,
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
