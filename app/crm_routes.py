"""CRM API: domains, compliant scraping, contacts, suppression, campaigns
(with the review->approve compliance gate), queue, sending, and analytics."""
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db, SessionLocal
from .crm_models import Domain, Contact, Suppression, Campaign, QueueItem, CompanyProfile
from . import compliance, scraper, campaign_engine, replies, warmup

router = APIRouter(prefix="/crm", tags=["crm"])


# ---------------- company profile (one-time) ----------------

class ProfileIn(BaseModel):
    company_name: str
    website_url: str
    business_address: str
    sender_name: str
    reply_to_email: str


@router.get("/company-profile")
def get_company_profile(db: Session = Depends(get_db)):
    p = compliance.get_profile(db)
    if not p:
        return {"completed": False, "missing": [m for _, m in compliance.REQUIRED_PROFILE_FIELDS]}
    return {"completed": p.completed, "company_name": p.company_name, "website_url": p.website_url,
            "business_address": p.business_address, "sender_name": p.sender_name,
            "reply_to_email": p.reply_to_email, "missing": compliance.profile_missing(p)}


@router.post("/company-profile")
def save_company_profile(data: ProfileIn, db: Session = Depends(get_db)):
    if not compliance.valid_email(data.reply_to_email):
        raise HTTPException(400, "Reply-to email is not valid.")
    p = db.get(CompanyProfile, 1)
    if not p:
        p = CompanyProfile(id=1)
        db.add(p)
    for k, v in data.model_dump().items():
        setattr(p, k, v.strip())
    p.completed = len(compliance.profile_missing(p)) == 0
    db.commit()
    return {"completed": p.completed, "missing": compliance.profile_missing(p)}


# ---------------- domains + scraping ----------------

class DomainsIn(BaseModel):
    domains: list[str]
    mode: str = "vendor"


@router.post("/domains")
def upload_domains(data: DomainsIn, db: Session = Depends(get_db)):
    added = 0
    for raw in data.domains:
        d = raw.strip().lower().replace("www.", "")
        if not d:
            continue
        if not db.query(Domain).filter(Domain.domain == d).first():
            db.add(Domain(domain=d, mode=data.mode))
            added += 1
    db.commit()
    return {"added": added}


@router.post("/scrape")
def run_scrape(mode: str = "vendor", limit: int = 50, db: Session = Depends(get_db)):
    """Scrape this mode's pending domains for their OWN published business addresses.
    Dedups against existing contacts and skips suppressed emails."""
    pending = (db.query(Domain)
               .filter(Domain.status == "pending", Domain.mode == mode)
               .limit(limit).all())
    total_contacts = 0
    for dom in pending:
        result = scraper.extract_domain(dom.domain)
        found = 0
        for c in result["contacts"]:
            email = c["email"]
            if compliance.is_suppressed(db, email):
                continue
            if db.query(Contact).filter(Contact.email == email).first():
                continue  # dedup
            db.add(Contact(email=email, domain=c["domain"], mode=dom.mode,
                           source_url=c["source_url"],
                           role_based=c["role_based"], mx_ok=c["mx_ok"]))
            found += 1
        dom.status = result["status"] if not result["contacts"] else "scraped"
        dom.contacts_found = found
        total_contacts += found
        db.commit()
    return {"domains_processed": len(pending), "new_contacts": total_contacts}


@router.get("/contacts")
def list_contacts(mode: str = "", db: Session = Depends(get_db)):
    q = db.query(Contact)
    if mode:
        q = q.filter(Contact.mode == mode)
    rows = q.all()
    return [{"id": c.id, "email": c.email, "domain": c.domain, "mode": c.mode,
             "role_based": c.role_based, "mx_ok": c.mx_ok, "status": c.status,
             "source_url": c.source_url} for c in rows]


# ---------------- suppression ----------------

class SuppressIn(BaseModel):
    email: str
    reason: str = "manual"


@router.post("/suppression")
def add_suppress(data: SuppressIn, db: Session = Depends(get_db)):
    if not compliance.valid_email(data.email):
        raise HTTPException(400, "Invalid email")
    compliance.add_suppression(db, data.email, data.reason)
    return {"suppressed": data.email.lower()}


@router.get("/suppression")
def list_suppress(db: Session = Depends(get_db)):
    return [{"email": s.email, "reason": s.reason} for s in db.query(Suppression).all()]


# ---------------- campaigns + compliance gate ----------------

class CampaignIn(BaseModel):
    name: str
    mode: str = "vendor"
    subject: str = ""
    from_name: str = ""
    company: str = ""
    postal_address: str = ""
    reason_for_contact: str = ""
    body_html: str = ""
    unsubscribe_url: str = ""
    per_sender_daily_cap: int = 100
    min_delay_sec: int = 25
    max_delay_sec: int = 60


@router.post("/campaigns")
def create_campaign(data: CampaignIn, db: Session = Depends(get_db)):
    c = Campaign(**data.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "status": c.status, "mode": c.mode}


@router.get("/campaigns")
def list_campaigns(mode: str = "", db: Session = Depends(get_db)):
    q = db.query(Campaign)
    if mode:
        q = q.filter(Campaign.mode == mode)
    return [{"id": c.id, "name": c.name, "mode": c.mode, "status": c.status,
             "lawful_basis_confirmed": c.lawful_basis_confirmed} for c in q.all()]


@router.post("/campaigns/{cid}/review")
def review_campaign(cid: int, db: Session = Depends(get_db)):
    """Campaign review step: reports what's missing before it can be approved."""
    c = db.get(Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    prof_miss = compliance.profile_missing(compliance.get_profile(db))
    miss = compliance.missing_fields(c)
    ready = not miss and not prof_miss
    if ready:
        c.status = "pending_review"; db.commit()
    return {"ready_to_approve": ready, "missing_campaign_fields": miss,
            "missing_company_profile": prof_miss,
            "needs_lawful_basis_confirmation": not c.lawful_basis_confirmed}


class ApproveIn(BaseModel):
    lawful_basis_confirmed: bool = False


@router.post("/campaigns/{cid}/approve")
def approve_campaign(cid: int, data: ApproveIn, db: Session = Depends(get_db)):
    """Hard gate: approval requires all fields present AND explicit lawful-basis confirmation."""
    c = db.get(Campaign, cid)
    if not c:
        raise HTTPException(404, "Campaign not found")
    miss = compliance.missing_fields(c)
    if miss:
        raise HTTPException(400, "Cannot approve — missing: " + ", ".join(miss))
    if not data.lawful_basis_confirmed:
        raise HTTPException(400, "You must confirm you have a lawful basis / permission to contact these businesses.")
    c.lawful_basis_confirmed = True
    c.status = "approved"
    db.commit()
    return {"id": c.id, "status": c.status}


@router.post("/campaigns/{cid}/build-queue")
def build_queue(cid: int, db: Session = Depends(get_db)):
    try:
        return campaign_engine.build_queue(db, cid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/campaigns/{cid}/send-batch")
def send_batch(cid: int, batch_size: int = 20, db: Session = Depends(get_db)):
    try:
        return campaign_engine.send_batch(db, cid, batch_size)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/campaigns/{cid}/analytics")
def campaign_analytics(cid: int, db: Session = Depends(get_db)):
    return campaign_engine.analytics(db, cid)


# ---------------- replies + opt-out ----------------

@router.post("/replies/scan")
def scan_replies(db: Session = Depends(get_db)):
    """Read OAuth senders' inboxes; log replies and auto-handle opt-outs."""
    return replies.scan_replies(db)


class ManualReplyIn(BaseModel):
    email: str
    text: str


@router.post("/replies/manual")
def manual_reply(data: ManualReplyIn, db: Session = Depends(get_db)):
    """Record a reply by hand (e.g. for app-password senders). Applies opt-out wording."""
    contact = db.query(Contact).filter(Contact.email == data.email.lower()).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    cid = replies._campaign_for(db, contact.id)
    status = replies.apply_reply(db, contact, cid, 0, data.text)
    return {"email": contact.email, "status": status}


@router.get("/campaigns/{cid}/recipients")
def campaign_recipients(cid: int, db: Session = Depends(get_db)):
    """Live status per recipient for the campaign table."""
    label = {"new": "Queued", "queued": "Queued", "sent": "Sent", "failed": "Failed",
             "replied": "Replied", "unsubscribed": "Unsubscribed", "not_interested": "Not Interested"}
    out = []
    items = db.query(QueueItem).filter(QueueItem.campaign_id == cid).all()
    for it in items:
        ct = db.get(Contact, it.contact_id)
        if not ct:
            continue
        # contact-level status (replied/unsub/not_interested) wins over queue status
        status = ct.status if ct.status in ("replied", "unsubscribed", "not_interested") else it.status
        out.append({"email": ct.email, "status": label.get(status, status.title()),
                    "sent_at": it.sent_at.isoformat() if it.sent_at else None})
    return out


# ---------------- warmup ----------------

@router.get("/warmup/status")
def warmup_status(db: Session = Depends(get_db)):
    return warmup.warmup_status(db)


@router.post("/warmup/run")
def warmup_run(max_sends: int = 10, db: Session = Depends(get_db)):
    """Send a small batch of warmup emails between the user's own connected inboxes."""
    return warmup.run_warmup(db, max_sends)


# ---------------- compliance dashboard + full stats ----------------

@router.get("/dashboard")
def compliance_dashboard(mode: str = "", db: Session = Depends(get_db)):
    from .crm_models import EventLog, ScraperJob, ScraperResult
    from .database import Sender
    try:
        return _compliance_dashboard_impl(mode, db)
    except Exception as e:
        import traceback
        print(f"[dashboard] ERROR for mode={mode}: {e}")
        traceback.print_exc()
        # Minimal safe payload so the UI still renders
        return {"mode": mode or "all", "company_profile_completed": False,
                "statuses": {"Sent":0,"Opened":0,"Replied":0,"Failed":0,
                             "Unsubscribed":0,"Not Interested":0},
                "senders": [], "error": str(e)}


def _compliance_dashboard_impl(mode, db):
    from .crm_models import EventLog, ScraperJob, ScraperResult
    from .database import Sender
    cq = db.query(Campaign)
    if mode:
        cq = cq.filter(Campaign.mode == mode)
    campaign_ids = [c.id for c in cq.all()]

    totals = {"sent": 0, "opened": 0, "replied": 0, "failed": 0, "unsubscribed": 0, "not_interested": 0}
    eq = db.query(EventLog)
    if mode:
        eq = eq.filter(EventLog.campaign_id.in_(campaign_ids or [-1]))
    for ev in eq.all():
        if ev.type in totals:
            totals[ev.type] += 1

    contacts_q = db.query(Contact)
    if mode:
        contacts_q = contacts_q.filter(Contact.mode == mode)

    # scraper stats (mode-aware)
    scraper_q = db.query(ScraperJob)
    if mode:
        scraper_q = scraper_q.filter(ScraperJob.mode == mode)
    scraper_jobs_all = scraper_q.all()
    total_scraped_emails = sum(j.emails_found for j in scraper_jobs_all)
    total_domains_scraped = sum(j.total for j in scraper_jobs_all)

    # per-sender stats
    senders = db.query(Sender).all()
    sender_stats = []
    for s in senders:
        sender_sent = db.query(EventLog).filter(EventLog.sender_id == s.id, EventLog.type == "sent").count()
        sender_failed = db.query(EventLog).filter(EventLog.sender_id == s.id, EventLog.type == "failed").count()
        sender_replied = db.query(EventLog).filter(EventLog.sender_id == s.id, EventLog.type == "replied").count()
        sender_stats.append({
            "id": s.id, "email": s.email, "name": s.name or s.email.split("@")[0],
            "method": s.method, "health": s.health, "status": s.status,
            "sent": sender_sent, "failed": sender_failed, "replied": sender_replied,
            "sent_today": s.sent_today, "total_sent": s.total_sent, "daily_cap": s.daily_cap,
        })

    prof = compliance.get_profile(db)
    return {
        "mode": mode or "all",
        "company_profile_completed": bool(prof and prof.completed),
        "statuses": {
            "Sent": totals["sent"], "Opened": totals["opened"], "Replied": totals["replied"],
            "Failed": totals["failed"], "Unsubscribed": totals["unsubscribed"],
            "Not Interested": totals["not_interested"],
        },
        "contacts": contacts_q.count(),
        "suppressed": db.query(Suppression).count(),
        "campaigns": len(campaign_ids),
        "approved_campaigns": cq.filter(Campaign.status.in_(["approved", "sending", "completed"])).count(),
        "unsubscribe_rate": round(totals["unsubscribed"] / totals["sent"] * 100, 2) if totals["sent"] else 0.0,
        "scraper": {
            "total_jobs": len(scraper_jobs_all),
            "total_domains": total_domains_scraped,
            "total_emails_found": total_scraped_emails,
        },
        "sender_stats": sender_stats,
    }


@router.get("/stats/scraper-history")
def scraper_history(mode: str = "", db: Session = Depends(get_db)):
    """All scraper jobs with their results — for the expandable stats view."""
    from .crm_models import ScraperJob, ScraperResult
    q = db.query(ScraperJob)
    if mode:
        q = q.filter(ScraperJob.mode == mode)
    jobs = q.order_by(ScraperJob.id.desc()).all()
    out = []
    for j in jobs:
        results = db.query(ScraperResult).filter(ScraperResult.job_id == j.id).all()
        out.append({
            "id": j.id, "name": j.name, "mode": j.mode, "status": j.status,
            "total": j.total, "done": j.done, "emails_found": j.emails_found,
            "created_at": j.created_at.isoformat(),
            "emails": [{"email": r.email, "domain": r.domain, "email_type": r.email_type,
                        "confidence": r.confidence, "source_url": r.source_url}
                       for r in results],
        })
    return out


@router.get("/stats/sender-history")
def sender_history(db: Session = Depends(get_db)):
    """Per-sender detailed send log — for expandable sender stats."""
    from .crm_models import EventLog
    from .database import Sender
    senders = db.query(Sender).all()
    out = []
    for s in senders:
        events = (db.query(EventLog).filter(EventLog.sender_id == s.id)
                  .order_by(EventLog.id.desc()).limit(200).all())
        out.append({
            "id": s.id, "email": s.email, "name": s.name or s.email.split("@")[0],
            "method": s.method, "health": s.health, "status": s.status,
            "total_sent": s.total_sent, "sent_today": s.sent_today, "daily_cap": s.daily_cap,
            "events": [{"type": e.type, "campaign_id": e.campaign_id,
                        "created_at": e.created_at.isoformat()} for e in events],
        })
    return out


# ============ OUTREACH SHEET (Campaign Send List) ============

@router.post("/outreach/add-from-scraper")
def add_scraper_results_to_outreach(mode: str = "vendor", job_id: int = 0, db: Session = Depends(get_db)):
    """Add scraped emails to this mode's send list.

    Safe to click ANY TIME — including while the scraper is still running.
    Whatever has been found so far gets added; clicking again later adds only
    the new ones. Never creates duplicates and never re-adds unsubscribed
    addresses. Data is per-mode, so vendor/client/blog lists stay separate.
    """
    from .crm_models import ScraperResult, ScraperJob, OutreachEntry

    if job_id > 0:
        # Only allow a job that belongs to THIS mode (keeps modes separate)
        job = db.get(ScraperJob, job_id)
        if not job or (job.mode or "vendor") != mode:
            return {"added": 0, "total": db.query(OutreachEntry).filter(
                OutreachEntry.mode == mode).count(),
                "error": "Job not found for this dashboard."}
        results = db.query(ScraperResult).filter(ScraperResult.job_id == job_id).all()
    else:
        job_ids = [j.id for j in db.query(ScraperJob).filter(ScraperJob.mode == mode).all()]
        results = db.query(ScraperResult).filter(ScraperResult.job_id.in_(job_ids or [-1])).all()

    # Load ALL existing emails for this mode in ONE query (was one query per
    # email — far too slow for thousands of results).
    existing = {e[0].strip().lower() for e in db.query(OutreachEntry.email).filter(
        OutreachEntry.mode == mode).all() if e[0]}
    # Same for the unsubscribe list — one query, not one per email. Querying per
    # email made this endpoint hang for minutes on big lists (and it competes
    # with the scraper for the database).
    from .crm_models import Suppression
    suppressed = {s[0].strip().lower() for s in db.query(Suppression.email).all() if s[0]}

    added = skipped_dup = skipped_suppressed = 0
    new_rows = []
    for r in results:
        email = (r.email or "").strip().lower()
        if not email or "@" not in email:
            continue
        if email in existing:          # already in list (or seen earlier in this batch)
            skipped_dup += 1
            continue
        if email in suppressed:        # unsubscribed — never re-add
            skipped_suppressed += 1
            continue
        new_rows.append(OutreachEntry(mode=mode, email=email, domain=r.domain,
            email_type=r.email_type, confidence=r.confidence, source_url=r.source_url))
        existing.add(email)            # prevents duplicates within this batch too
        added += 1

    # Insert in chunks so one huge transaction doesn't hold the write lock
    # while the scraper is running.
    CHUNK = 500
    for i in range(0, len(new_rows), CHUNK):
        db.add_all(new_rows[i:i + CHUNK])
        db.commit()
    if not new_rows:
        db.commit()

    total = db.query(OutreachEntry).filter(OutreachEntry.mode == mode).count()
    return {"added": added, "total": total,
            "skipped_duplicates": skipped_dup,
            "skipped_unsubscribed": skipped_suppressed}


@router.get("/outreach/list")
def list_outreach(mode: str = "vendor", page: int = 1, limit: int = 100, status: str = "", db: Session = Depends(get_db)):
    """Paginated outreach sheet with live status and optional filter."""
    from .crm_models import OutreachEntry
    q = db.query(OutreachEntry).filter(OutreachEntry.mode == mode)
    if status:
        q = q.filter(OutreachEntry.status == status)
    total = q.count()
    entries = q.order_by(OutreachEntry.id.desc()).offset((page-1)*limit).limit(limit).all()
    return {
        "total": total, "page": page, "limit": limit,
        "entries": [{"id":e.id,"email":e.email,"domain":e.domain,"email_type":e.email_type,
                     "confidence":e.confidence,"source_url":e.source_url,"status":e.status,
                     "sent_at":e.sent_at.isoformat() if e.sent_at else None,
                     "opened_at":e.opened_at.isoformat() if e.opened_at else None,
                     "replied_at":e.replied_at.isoformat() if e.replied_at else None,
                     "sender_email":e.sender_email,"subject":e.subject,
                     "created_at":e.created_at.isoformat()} for e in entries]
    }


@router.get("/outreach/stats")
def outreach_stats(mode: str = "vendor", db: Session = Depends(get_db)):
    """Live stats for the outreach sheet. Hardened so a single bad row can
    never 500 the whole endpoint."""
    from .crm_models import OutreachEntry
    try:
        q = db.query(OutreachEntry).filter(OutreachEntry.mode == mode)
        total = q.count()
        sent = q.filter(OutreachEntry.status.in_(["sent","opened","replied"])).count()
        opened = q.filter(OutreachEntry.status.in_(["opened","replied"])).count()
        replied = q.filter(OutreachEntry.status == "replied").count()
        bounced = q.filter(OutreachEntry.status == "bounced").count()
        pending = q.filter(OutreachEntry.status == "pending").count()
        return {"total":total,"pending":pending,"sent":sent,"opened":opened,
                "replied":replied,"bounced":bounced,
                "open_rate":round(opened/max(1,sent)*100,1),
                "reply_rate":round(replied/max(1,sent)*100,1)}
    except Exception as e:
        import traceback
        print(f"[outreach_stats] ERROR for mode={mode}: {e}")
        traceback.print_exc()
        # Return zeros instead of 500 so the dashboard still renders
        return {"total":0,"pending":0,"sent":0,"opened":0,"replied":0,
                "bounced":0,"open_rate":0.0,"reply_rate":0.0,"error":str(e)}


@router.get("/outreach/export")
def export_outreach(mode: str = "vendor", format: str = "csv", db: Session = Depends(get_db)):
    """Export outreach sheet as CSV or Excel."""
    from .crm_models import OutreachEntry
    from fastapi.responses import Response
    entries = db.query(OutreachEntry).filter(OutreachEntry.mode == mode).order_by(OutreachEntry.id).all()
    if format == "xlsx":
        from openpyxl import Workbook
        from io import BytesIO
        wb = Workbook(); ws = wb.active
        ws.append(["Email","Domain","Type","Confidence","Status","Sent","Opened","Replied","Source","Added"])
        for e in entries:
            ws.append([e.email,e.domain,e.email_type,e.confidence,e.status,
                       str(e.sent_at or ""),str(e.opened_at or ""),str(e.replied_at or ""),
                       e.source_url,str(e.created_at)])
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        return Response(content=buf.read(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition":"attachment; filename=outreach.xlsx"})
    # CSV
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Email","Domain","Type","Confidence","Status","Sent","Opened","Replied","Source","Added"])
    for e in entries:
        w.writerow([e.email,e.domain,e.email_type,e.confidence,e.status,
                    e.sent_at or "",e.opened_at or "",e.replied_at or "",e.source_url,e.created_at])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition":"attachment; filename=outreach.csv"})


# ============ AUTO-CAMPAIGN BUILDER ============

@router.post("/outreach/build-campaigns")
def build_campaigns(mode: str = "vendor", db: Session = Depends(get_db)):
    """Auto-create campaigns from pending outreach emails.
    Each sender gets one campaign with emails up to their daily_cap."""
    from .crm_models import OutreachEntry
    from .database import Sender

    senders = db.query(Sender).filter(Sender.mode == mode).all()
    if not senders:
        return {"error": "No senders in this mode. Add senders first.", "campaigns": []}

    pending = db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode, OutreachEntry.status == "pending"
    ).order_by(OutreachEntry.id).all()

    if not pending:
        return {"error": "No pending emails in send list.", "campaigns": []}

    created = []
    idx = 0
    for sender in senders:
        if idx >= len(pending):
            break
        cap = sender.daily_cap or 150
        batch = pending[idx:idx + cap]
        idx += cap

        # Create campaign
        camp = Campaign(
            mode=mode,
            name=f"Campaign — {sender.email} ({len(batch)} emails)",
            status="ready",
        )
        db.add(camp)
        db.commit()
        db.refresh(camp)

        # Link emails to this campaign
        for entry in batch:
            entry.status = "queued"
            entry.sender_email = sender.email
            db.add(QueueItem(
                campaign_id=camp.id,
                contact_id=0,
                sender_id=sender.id,
                email=entry.email,
                subject="",
                body_html="",
            ))
        db.commit()

        created.append({
            "campaign_id": camp.id,
            "sender": sender.email,
            "emails": len(batch),
            "status": "ready"
        })

    remaining = len(pending) - idx
    return {"campaigns": created, "remaining_pending": remaining,
            "total_queued": idx}


@router.get("/outreach/campaigns")
def list_outreach_campaigns(mode: str = "vendor", db: Session = Depends(get_db)):
    """List all campaigns with stats."""
    from .crm_models import OutreachEntry
    camps = db.query(Campaign).filter(Campaign.mode == mode).order_by(Campaign.id.desc()).all()
    out = []
    for c in camps:
        # Count statuses from outreach entries linked to this campaign's sender
        total_queued = db.query(QueueItem).filter(QueueItem.campaign_id == c.id).count()
        sent = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "sent").count()
        opened = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "opened").count()
        replied = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "replied").count()
        failed = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "failed").count()
        out.append({
            "id": c.id, "name": c.name, "status": c.status, "mode": c.mode,
            "total": total_queued, "sent": sent, "opened": opened,
            "replied": replied, "failed": failed,
            "created_at": c.created_at.isoformat() if c.created_at else ""
        })
    return out


# ============ SEND ENGINE ============

@router.post("/send/start")
def start_sending(campaign_id: int, mode: str = "vendor", 
                  emails_per_batch: int = 10, delay_seconds: int = 60,
                  scheduled_time: str = None, db: Session = Depends(get_db)):
    """Start sending emails for a campaign with rate control and optional scheduling."""
    from . import send_engine
    result = send_engine.start_campaign_send(
        campaign_id=campaign_id, mode=mode,
        emails_per_batch=emails_per_batch,
        delay_seconds=delay_seconds,
        scheduled_time=scheduled_time
    )
    return result


@router.post("/send/stop")
def stop_sending(campaign_id: int, db: Session = Depends(get_db)):
    """Stop a running campaign."""
    from . import send_engine
    return send_engine.stop_campaign(campaign_id)


# ============ TEMPLATES ============

@router.get("/templates")
def list_templates(mode: str = "client"):
    """Return outreach templates for the mode: client (guest post service) or vendor (asking sites)."""
    if mode == "vendor":
        from .vendor_templates import VENDOR_TEMPLATES
        return [{"id": i+1, "subject": t["subject"], "body": t["body"]} for i, t in enumerate(VENDOR_TEMPLATES)]
    from .email_templates import TEMPLATES
    return [{"id": i+1, "subject": t["subject"], "body": t["body"]} for i, t in enumerate(TEMPLATES)]


@router.post("/outreach/import-csv")
def import_csv_to_outreach(mode: str = "client", db: Session = Depends(get_db)):
    """Import emails from scraper_6__3_.csv in the working directory."""
    import csv, os
    from .crm_models import OutreachEntry
    # Try multiple possible locations
    paths = ["scraper_6__3_.csv", "app/scraper_6__3_.csv", "../scraper_6__3_.csv",
             os.path.expanduser("~/Desktop/files/scraper_6__3_.csv"),
             "C:/Users/Dell/Desktop/files/scraper_6__3_.csv",
             "C:/Users/Dell/Downloads/scraper_6__3_.csv"]
    csv_path = None
    for p in paths:
        if os.path.exists(p):
            csv_path = p; break
    if not csv_path:
        return {"error": "CSV file not found. Place scraper_6__3_.csv in C:\\Users\\Dell\\Desktop\\files\\", "paths_checked": paths}
    added = 0
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            email = (row.get('Email') or '').strip()
            domain = (row.get('Domain') or '').strip()
            if not email or '@' not in email: continue
            exists = db.query(OutreachEntry).filter(OutreachEntry.email == email, OutreachEntry.mode == mode).first()
            if not exists:
                db.add(OutreachEntry(mode=mode, email=email, domain=domain,
                    email_type=row.get('Email Type','domain_email'),
                    confidence=row.get('Confidence','medium'),
                    source_url=row.get('Source URL',''), status='pending'))
                added += 1
    db.commit()
    total = db.query(OutreachEntry).filter(OutreachEntry.mode == mode).count()
    return {"added": added, "total": total, "file": csv_path}


@router.post("/outreach/verify")
def verify_outreach_emails(mode: str = "vendor", db: Session = Depends(get_db)):
    """Verify all pending emails (MX check). Marks invalid ones as bounced."""
    from .crm_models import OutreachEntry
    from .email_verify import quick_verify
    pending = db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode, OutreachEntry.status == "pending").all()
    valid = 0; invalid = 0
    for entry in pending:
        is_valid, reason = quick_verify(entry.email)
        if not is_valid:
            entry.status = "bounced"
            invalid += 1
        else:
            valid += 1
    db.commit()
    return {"checked": len(pending), "valid": valid, "invalid": invalid}


@router.get("/senders/activity")
def sender_activity(mode: str = "vendor", page: int = 1, limit: int = 100,
                    sender: str = "", db: Session = Depends(get_db)):
    """Live sending history — which email sent via which sender, status, dates."""
    from .crm_models import OutreachEntry
    q = db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode,
        OutreachEntry.status.in_(["sent", "opened", "replied", "bounced"])
    )
    if sender:
        q = q.filter(OutreachEntry.sender_email == sender)
    total = q.count()
    entries = q.order_by(OutreachEntry.sent_at.desc()).offset((page-1)*limit).limit(limit).all()
    return {
        "total": total, "page": page,
        "entries": [{"email": e.email, "domain": e.domain,
                     "sender_email": e.sender_email or "—",
                     "status": e.status, "subject": e.subject,
                     "sent_at": e.sent_at.isoformat() if e.sent_at else None,
                     "opened_at": e.opened_at.isoformat() if e.opened_at else None,
                     "replied_at": e.replied_at.isoformat() if e.replied_at else None
                     } for e in entries]
    }


# ============ WARMUP ENGINE ============

@router.post("/warmup/start")
def start_warmup_engine(mode: str = "client", interval_minutes: int = 90):
    """Start real-time warmup — senders email each other, rescue from spam, reply."""
    from . import warmup_engine
    return warmup_engine.start_warmup(mode, interval_minutes)


@router.post("/warmup/stop")
def stop_warmup_engine():
    from . import warmup_engine
    return warmup_engine.stop_warmup()


@router.post("/warmup/run-once")
def run_warmup_once(mode: str = "client"):
    """Run one warmup cycle immediately (for testing)."""
    from . import warmup_engine
    return warmup_engine.run_warmup_cycle(mode)


@router.get("/warmup/engine-status")
def get_warmup_engine_status(mode: str = "client", db: Session = Depends(get_db)):
    from . import warmup_engine
    from .database import Sender
    status = warmup_engine.warmup_status()
    pool = warmup_engine.pool_info(db)
    senders = db.query(Sender).filter(Sender.mode == mode, Sender.warmup == True).all()
    return {
        "running": status["running"],
        "active_senders": len(senders),
        "pool_size": pool["pool_size"],
        "pool_domains": pool["domains"],
        "can_warmup": pool["can_warmup"],
        "domain_breakdown": pool["domain_breakdown"],
        "senders": [{"email": s.email, "warmup_sent_today": s.warmup_sent_today or 0,
                     "total_sent": s.total_sent or 0} for s in senders]
    }


# ============ FULL CAMPAIGN SYSTEM (autopilot, scheduling, sender selection) ============

@router.post("/campaign/create")
def create_campaign(
    name: str, mode: str = "vendor",
    sender_emails: str = "",       # comma-separated: "a@x.com,b@y.com"
    emails_per_batch: int = 10,
    delay_seconds: int = 30,
    min_delay: int = 0, max_delay: int = 0,   # random gap range
    total_target: int = 0,          # 0 = all pending
    scheduled_time: str = "",       # ISO datetime, empty = manual
    autopilot: bool = False,
    db: Session = Depends(get_db)
):
    """Create a campaign with full control: which senders, timing, autopilot."""
    from .crm_models import OutreachEntry
    pending = db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode, OutreachEntry.status == "pending").count()
    if pending == 0:
        return {"error": "No pending emails in send list."}
    target = total_target if total_target > 0 else pending
    # Random gap range (default: build from delay_seconds)
    if min_delay <= 0:
        min_delay = max(10, int(delay_seconds * 0.5))
    if max_delay <= 0:
        max_delay = int(delay_seconds * 1.35)

    camp = Campaign(
        name=name, mode=mode, status="scheduled" if scheduled_time else "ready",
        sender_emails=sender_emails, emails_per_batch=emails_per_batch,
        delay_seconds=delay_seconds, min_delay_sec=min_delay, max_delay_sec=max_delay,
        scheduled_time=scheduled_time,
        autopilot=autopilot, total_target=target,
    )
    db.add(camp); db.commit(); db.refresh(camp)
    return {"campaign_id": camp.id, "name": camp.name, "target": target,
            "status": camp.status, "autopilot": autopilot,
            "gap": f"{min_delay}-{max_delay}s random"}


@router.get("/campaign/list")
def list_all_campaigns(mode: str = "vendor", db: Session = Depends(get_db)):
    """List all campaigns with full details."""
    camps = db.query(Campaign).filter(Campaign.mode == mode).order_by(Campaign.id.desc()).all()
    from .crm_models import EventLog, QueueItem
    out = []
    for c in camps:
        sent = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "sent").count()
        opened = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "opened").count()
        replied = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "replied").count()
        failed = db.query(EventLog).filter(EventLog.campaign_id == c.id, EventLog.type == "failed").count()
        out.append({
            "id": c.id, "name": c.name, "status": c.status,
            "senders": c.sender_emails or "all", "target": c.total_target,
            "sent": sent, "opened": opened, "replied": replied, "failed": failed,
            "batch": c.emails_per_batch, "delay": c.delay_seconds,
            "scheduled_time": c.scheduled_time, "autopilot": c.autopilot,
            "created_at": c.created_at.isoformat() if c.created_at else ""
        })
    return out


@router.post("/campaign/{campaign_id}/start")
def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Start (or schedule) a specific campaign."""
    from . import send_engine
    camp = db.get(Campaign, campaign_id)
    if not camp:
        return {"error": "Campaign not found"}
    result = send_engine.start_campaign_send(
        campaign_id=campaign_id, mode=camp.mode,
        emails_per_batch=camp.emails_per_batch,
        delay_seconds=camp.delay_seconds,
        min_delay=camp.min_delay_sec or 0,
        max_delay=camp.max_delay_sec or 0,
        scheduled_time=camp.scheduled_time or None,
        sender_filter=camp.sender_emails or None,
        total_target=camp.total_target,
        autopilot=camp.autopilot,
    )
    return result


@router.post("/campaign/{campaign_id}/stop")
def stop_campaign_ep(campaign_id: int, db: Session = Depends(get_db)):
    from . import send_engine
    return send_engine.stop_campaign(campaign_id)


@router.delete("/campaign/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    camp = db.get(Campaign, campaign_id)
    if camp:
        db.delete(camp); db.commit()
    return {"deleted": campaign_id}


# ============ BLOG RESEARCH (client-hunting via external links) ============

_blog_threads = {}
_blog_stop = {}


@router.post("/replies/check")
def check_replies_now(days: int = 14, db: Session = Depends(get_db)):
    """Scan every sender's inbox now and mark anyone who replied.
    Works locally — the server connects out to Gmail, no public URL needed."""
    from . import reply_tracker
    try:
        return reply_tracker.check_replies(db, days=days)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"replies_found": 0, "error": str(e)}


@router.get("/replies/status")
def replies_status():
    """Is the automatic reply checker running?"""
    from . import reply_tracker
    t = reply_tracker._thread
    return {"running": bool(t is not None and t.is_alive())}


@router.post("/blog/check-sites")
def check_blog_sites(sites: str = ""):
    """Pre-check sites before research. Warns about giant portals / aggregators
    (MSN, Yahoo, Forbes...) and unreachable sites so the user doesn't waste time.
    Returns a per-site verdict."""
    from . import blog_research
    site_list = [s.strip() for s in re.split(r"[,\n]", sites) if s.strip()]
    results = []
    warnings = 0
    for s in site_list:
        verdict = blog_research.check_site(s)
        if not verdict["ok"]:
            warnings += 1
        results.append({"site": s, **verdict})
    return {"results": results, "total": len(site_list),
            "warnings": warnings,
            "all_ok": warnings == 0}


@router.post("/blog/create")
def create_blog_job(name: str = "", sites: str = "", time_range: str = "1m",
                    max_articles: int = 150, autopilot: bool = False,
                    db: Session = Depends(get_db)):
    """Create a blog research job. sites = comma/newline separated domains."""
    from .crm_models import BlogResearchJob
    site_list = [s.strip() for s in re.split(r"[,\n]", sites) if s.strip()]
    if not site_list:
        return {"error": "Add at least one blog site."}
    job = BlogResearchJob(
        name=name or f"Research {datetime.utcnow().strftime('%b %d')}",
        sites=",".join(site_list), time_range=time_range,
        max_articles=max_articles, autopilot=autopilot,
        total_sites=len(site_list), status="pending",
    )
    db.add(job); db.commit(); db.refresh(job)
    return {"job_id": job.id, "name": job.name, "total_sites": len(site_list),
            "time_range": time_range}


@router.post("/blog/{job_id}/start")
def start_blog_job(job_id: int, db: Session = Depends(get_db)):
    """Start researching — find external links across all sites."""
    from .crm_models import BlogResearchJob, BlogResearchLink
    from . import blog_research
    job = db.get(BlogResearchJob, job_id)
    if not job:
        return {"error": "Job not found"}
    if job_id in _blog_threads:
        return {"error": "Already running"}

    _blog_stop[job_id] = {"stop": False}

    def _run():
        bg = None
        # Scraper pieces imported up-front so on_link can fire email scraping
        # the instant a link is found (concurrent with the rest of research).
        from . import scraper as _scraper
        from .crm_models import OutreachEntry
        from concurrent.futures import ThreadPoolExecutor as _TPE
        import threading as _threading

        # Thread-safe dedup: parallel workers reserve an email here BEFORE the
        # DB insert, so two workers scraping the same email can't both add it.
        _added_emails = set()
        _added_lock = _threading.Lock()

        def _is_junk_email(email, domain):
            """Reject clearly-bad emails like info@wikipedia.can."""
            if not email or "@" not in email:
                return True
            local, _, dom = email.partition("@")
            tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
            bad_tlds = {"can", "con", "cim", "cm", "co m", "comm", "net work",
                        "png", "jpg", "gif", "webp", "svg", "css", "js"}
            if tld.lower() in bad_tlds:
                return True
            if len(tld) < 2 or len(tld) > 10:
                return True
            return False

        def _scrape_one(link_id):
            """Scrape emails for one domain, add real ones to client list.
            Concurrency-safe (own DB session)."""
            s = SessionLocal()
            try:
                lk = s.get(BlogResearchLink, link_id)
                if not lk or lk.email_status != "pending":
                    return
                try:
                    res = _scraper.extract_domain(lk.target_domain)
                    contacts = res.get("contacts", [])
                    email = ""
                    for c in contacts:
                        cand = c.get("email", "")
                        if cand and not _is_junk_email(cand, lk.target_domain):
                            email = cand
                            break
                    if email:
                        email = email.strip().lower()  # normalize for dedupe
                        lk.email = email
                        lk.email_status = "found"
                        from . import compliance as _compliance
                        suppressed = _compliance.is_suppressed(s, email)

                        # Thread-safe reservation: only the first worker to see
                        # this email gets to try inserting it.
                        reserved = False
                        with _added_lock:
                            if email not in _added_emails:
                                _added_emails.add(email)
                                reserved = True

                        if suppressed:
                            print(f"[BlogResearch]   suppressed (skip): {email}")
                        elif not reserved:
                            print(f"[BlogResearch]   dup (skip): {email}")
                        else:
                            # Double-check DB (covers emails added in earlier jobs).
                            # Blog research keeps its OWN list (mode="blog"), separate
                            # from the client dashboard.
                            exists = s.query(OutreachEntry).filter(
                                OutreachEntry.mode == "blog",
                                OutreachEntry.email == email).first()
                            if exists:
                                print(f"[BlogResearch]   dup (skip): {email}")
                            else:
                                s.add(OutreachEntry(
                                    mode="blog", email=email, domain=lk.target_domain,
                                    email_type="blog_research", confidence="medium",
                                    source_url=lk.target_url, status="pending"))
                                print(f"[BlogResearch]   + added {lk.target_domain} -> {email}")
                    else:
                        lk.email_status = "no_email"
                        print(f"[BlogResearch]   no email: {lk.target_domain}")
                    s.commit()
                    jj = s.get(BlogResearchJob, job_id)
                    if jj:
                        jj.emails_found = s.query(BlogResearchLink).filter(
                            BlogResearchLink.job_id == job_id,
                            BlogResearchLink.email_status == "found").count()
                        s.commit()
                except Exception as ex_inner:
                    lk.email_status = "no_email"
                    s.commit()
                    print(f"[BlogResearch]   ! {lk.target_domain} error: {ex_inner}")
            finally:
                s.close()

        # Live email-scrape pool: fires as links come in, parallel to research
        email_pool = _TPE(max_workers=15)
        email_futures = []

        try:
            bg = SessionLocal()
            j = bg.get(BlogResearchJob, job_id)
            j.status = "running"; j.done_sites = 0; j.links_found = 0
            j.articles_found = 0; j.emails_found = 0; j.phase = "articles"
            bg.commit()
            sites = [s for s in j.sites.split(",") if s]
            seen_domains = set()  # global dedupe across all sites

            for site in sites:
                if _blog_stop.get(job_id, {}).get("stop"):
                    break

                # Live callback: article opened
                def on_article(article_url, count):
                    jj = bg.get(BlogResearchJob, job_id)
                    if jj:
                        jj.articles_found = (jj.articles_found or 0) + 1
                        jj.phase = "articles"
                        bg.commit()

                # Live callback: new link found -> save + fire email scrape NOW
                def on_link(r):
                    if r["target_domain"] in seen_domains:
                        return
                    seen_domains.add(r["target_domain"])
                    link = BlogResearchLink(
                        job_id=job_id, source_site=r["source_site"],
                        source_article=r["source_article"],
                        target_domain=r["target_domain"], target_url=r["target_url"],
                        published_date=r.get("published_date", ""),
                    )
                    bg.add(link)
                    bg.flush()  # assign link.id without a full commit
                    new_link_id = link.id
                    jj = bg.get(BlogResearchJob, job_id)
                    if jj:
                        jj.links_found = (jj.links_found or 0) + 1
                        jj.phase = "links"
                    bg.commit()
                    # AUTO email scrape: fire this domain into the pool immediately
                    # so email scraping runs concurrently with the research crawl.
                    if not _blog_stop.get(job_id, {}).get("stop"):
                        email_futures.append(email_pool.submit(_scrape_one, new_link_id))

                try:
                    print(f"[BlogResearch] Researching {site}...")
                    blog_research.research_site(
                        site, j.time_range, j.max_articles,
                        workers=10, on_article=on_article, on_link=on_link,
                        should_stop=lambda: _blog_stop.get(job_id, {}).get("stop", False))
                    print(f"[BlogResearch] Done {site}")
                except Exception as e:
                    import traceback
                    print(f"[BlogResearch] {site} ERROR: {e}")
                    traceback.print_exc()

                jj = bg.get(BlogResearchJob, job_id)
                jj.done_sites = (jj.done_sites or 0) + 1
                bg.commit()

            j = bg.get(BlogResearchJob, job_id)
            j.status = "done"; j.phase = "emails"
            j.links_found = bg.query(BlogResearchLink).filter(
                BlogResearchLink.job_id == job_id).count()
            bg.commit()
            print(f"[BlogResearch] Job {job_id} research complete: {j.links_found} links. "
                  f"Waiting for {len(email_futures)} live email scrapes...")

            # Wait for all the email scrapes that were fired live during research
            for f in email_futures:
                try:
                    f.result(timeout=60)
                except Exception:
                    pass

            # Safety net: any domain that never got scraped (e.g. fired after a
            # stop check) gets picked up here.
            leftover = bg.query(BlogResearchLink).filter(
                BlogResearchLink.job_id == job_id,
                BlogResearchLink.email_status == "pending").all()
            leftover_ids = [l.id for l in leftover]
            if leftover_ids:
                print(f"[BlogResearch] Scraping {len(leftover_ids)} leftover domains...")
                for lid in leftover_ids:
                    try:
                        email_pool.submit(_scrape_one, lid).result(timeout=60)
                    except Exception:
                        pass

            # Final count + mark fully done
            jj = bg.get(BlogResearchJob, job_id)
            if jj:
                jj.emails_found = bg.query(BlogResearchLink).filter(
                    BlogResearchLink.job_id == job_id,
                    BlogResearchLink.email_status == "found").count()
                jj.phase = "done"
                bg.commit()
            print(f"[BlogResearch] Job {job_id} FULLY done: {jj.emails_found if jj else 0} emails found")

            # ============ AUTOPILOT: auto-send if enabled ============
            # If this job was created with autopilot=ON, automatically create a
            # client campaign from the freshly-scraped emails and start sending —
            # no manual button needed. Research -> scrape -> send, fully hands-off.
            if jj and jj.autopilot:
                try:
                    from .crm_models import OutreachEntry
                    from .database import Sender
                    from . import send_engine

                    # Count pending BLOG emails ready to send (blog has its own list)
                    pending_count = bg.query(OutreachEntry).filter(
                        OutreachEntry.mode == "blog",
                        OutreachEntry.status == "pending").count()

                    # Senders: blog reuses the CLIENT senders (blog pitches clients).
                    # Fall back to any active sender if none are tagged client.
                    active_senders = bg.query(Sender).filter(
                        Sender.mode == "client",
                        Sender.status.notin_(["auth_failed", "verifying"])
                    ).all()
                    if not active_senders:
                        active_senders = bg.query(Sender).filter(
                            Sender.status.notin_(["auth_failed", "verifying"])
                        ).all()

                    if pending_count > 0 and active_senders:
                        camp = Campaign(
                            name=f"Autopilot — {jj.name} ({pending_count} emails)",
                            mode="blog",
                            status="ready",
                            sender_emails=",".join(s.email for s in active_senders),
                            emails_per_batch=10,
                            delay_seconds=30,
                            min_delay_sec=15,
                            max_delay_sec=40,
                            autopilot=True,
                            total_target=pending_count,
                        )
                        bg.add(camp)
                        bg.commit()
                        bg.refresh(camp)
                        print(f"[BlogResearch] Autopilot: created campaign #{camp.id}, "
                              f"starting send of {pending_count} emails via "
                              f"{len(active_senders)} sender(s)...")
                        # Kick off the send engine (runs in its own thread)
                        send_engine.start_campaign_send(
                            campaign_id=camp.id, mode="blog",
                            emails_per_batch=10, delay_seconds=30,
                            min_delay=15, max_delay=40,
                            sender_filter=camp.sender_emails,
                            total_target=pending_count,
                            autopilot=True,
                        )
                    else:
                        reason = ("no pending emails" if pending_count == 0
                                  else "no active senders")
                        print(f"[BlogResearch] Autopilot skipped: {reason}. "
                              f"Emails saved to blog list — send manually.")
                except Exception as ap_err:
                    print(f"[BlogResearch] Autopilot error: {ap_err}")
        except Exception as e:
            import traceback
            print(f"[BlogResearch] Job {job_id} FATAL ERROR: {e}")
            traceback.print_exc()
            # Mark job as error so it doesn't stay stuck on "pending"
            try:
                if bg is None:
                    bg = SessionLocal()
                jj = bg.get(BlogResearchJob, job_id)
                if jj:
                    jj.status = "error"
                    bg.commit()
            except Exception:
                pass
        finally:
            # Shut down the live email-scrape pool (don't leak threads)
            try:
                email_pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                try:
                    email_pool.shutdown(wait=False)
                except Exception:
                    pass
            if bg is not None:
                bg.close()
            _blog_threads.pop(job_id, None)
            _blog_stop.pop(job_id, None)

    import threading
    t = threading.Thread(target=_run, daemon=True)
    _blog_threads[job_id] = t
    t.start()
    return {"status": "started", "job_id": job_id}


@router.post("/blog/{job_id}/stop")
def stop_blog_job(job_id: int, db: Session = Depends(get_db)):
    """Immediately stop a running blog research job."""
    from .crm_models import BlogResearchJob
    # 1) Set the stop flag so the background thread halts at its next check
    if job_id in _blog_stop:
        _blog_stop[job_id]["stop"] = True
    # 2) Immediately reflect the stop in the DB so the UI updates on next poll
    job = db.get(BlogResearchJob, job_id)
    if job and job.status == "running":
        job.status = "stopped"
        job.phase = ""
        db.commit()
    return {"status": "stopped"}


@router.get("/blog/jobs")
def list_blog_jobs(db: Session = Depends(get_db)):
    from .crm_models import BlogResearchJob
    jobs = db.query(BlogResearchJob).order_by(BlogResearchJob.id.desc()).all()
    return [{"id": j.id, "name": j.name, "status": j.status,
             "total_sites": j.total_sites, "done_sites": j.done_sites,
             "articles_found": j.articles_found or 0,
             "links_found": j.links_found, "emails_found": j.emails_found or 0,
             "phase": j.phase or "", "time_range": j.time_range,
             "autopilot": j.autopilot,
             "created_at": j.created_at.isoformat() if j.created_at else ""} for j in jobs]


@router.get("/blog/{job_id}/links")
def blog_links(job_id: int, page: int = 1, limit: int = 100, db: Session = Depends(get_db)):
    from .crm_models import BlogResearchLink
    q = db.query(BlogResearchLink).filter(BlogResearchLink.job_id == job_id)
    total = q.count()
    links = q.order_by(BlogResearchLink.id.desc()).offset((page-1)*limit).limit(limit).all()
    return {"total": total, "page": page,
            "links": [{"id": l.id, "source_site": l.source_site,
                       "source_article": l.source_article,
                       "target_domain": l.target_domain, "target_url": l.target_url,
                       "email": l.email, "email_status": l.email_status,
                       "published_date": getattr(l, "published_date", "")} for l in links]}


@router.get("/blog/{job_id}/export")
def blog_export(job_id: int, format: str = "csv", only_emails: bool = False,
                db: Session = Depends(get_db)):
    """Export a blog research job's discovered links/prospects as CSV or Excel.
    only_emails=True -> just the rows where an email was found."""
    from .crm_models import BlogResearchLink, BlogResearchJob
    from fastapi.responses import Response

    job = db.get(BlogResearchJob, job_id)
    jobname = (job.name if job else f"job{job_id}").replace(" ", "_").replace("/", "-")

    q = db.query(BlogResearchLink).filter(BlogResearchLink.job_id == job_id)
    if only_emails:
        q = q.filter(BlogResearchLink.email_status == "found")
    links = q.order_by(BlogResearchLink.id).all()

    headers_row = ["From Site", "Published Date", "Source Article", "Target Domain",
                   "Target URL", "Email", "Email Status"]

    def row_of(l):
        return [l.source_site or "", getattr(l, "published_date", "") or "",
                l.source_article or "", l.target_domain or "",
                l.target_url or "", l.email or "", l.email_status or ""]

    if format == "xlsx":
        from openpyxl import Workbook
        from io import BytesIO
        wb = Workbook(); ws = wb.active; ws.title = "Prospects"
        ws.append(headers_row)
        for l in links:
            ws.append(row_of(l))
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=blog_{jobname}.xlsx"})

    # CSV
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers_row)
    for l in links:
        w.writerow(row_of(l))
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=blog_{jobname}.csv"})



    """Scrape emails from all discovered link domains (like the main scraper)."""
    from .crm_models import BlogResearchLink, OutreachEntry
    from . import scraper
    links = db.query(BlogResearchLink).filter(
        BlogResearchLink.job_id == job_id,
        BlogResearchLink.email_status == "pending").all()

    def _run():
        bg = SessionLocal()
        try:
            for link in bg.query(BlogResearchLink).filter(
                    BlogResearchLink.job_id == job_id,
                    BlogResearchLink.email_status == "pending").all():
                try:
                    result = scraper.extract_domain(link.target_domain, mode="client")
                    contacts = result.get("contacts", [])
                    if contacts:
                        email = (contacts[0].get("email", "") or "").strip().lower()
                        link.email = email
                        link.email_status = "found"
                        # Add to the BLOG send list (not client — blog keeps its own).
                        # Duplicate check must be mode-scoped too.
                        existing = bg.query(OutreachEntry).filter(
                            OutreachEntry.mode == "blog",
                            OutreachEntry.email == email).first()
                        if not existing and email:
                            bg.add(OutreachEntry(
                                mode="blog", email=email, domain=link.target_domain,
                                email_type="blog_research", confidence="medium",
                                source_url=link.target_url, status="pending"))
                    else:
                        link.email_status = "no_email"
                    bg.commit()
                except Exception as e:
                    link.email_status = "no_email"
                    bg.commit()
        finally:
            bg.close()

    import threading
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "scraping", "to_scrape": len(links)}


@router.delete("/blog/{job_id}")
def delete_blog_job(job_id: int, db: Session = Depends(get_db)):
    from .crm_models import BlogResearchJob, BlogResearchLink
    job = db.get(BlogResearchJob, job_id)
    if job:
        db.query(BlogResearchLink).filter(BlogResearchLink.job_id == job_id).delete()
        db.delete(job); db.commit()
    return {"deleted": job_id}


@router.post("/blog/migrate-from-client")
def blog_migrate_from_client(db: Session = Depends(get_db)):
    """One-time migration: move OLD blog-research emails that were saved under
    mode='client' (before blog got its own list) into mode='blog'. Skips any
    email that already exists in the blog list (no duplicates)."""
    from .crm_models import OutreachEntry

    # All client-mode entries that came from blog research
    old = db.query(OutreachEntry).filter(
        OutreachEntry.mode == "client",
        OutreachEntry.email_type == "blog_research").all()

    # Emails already present in the blog list (to avoid duplicates)
    existing_blog = {e.email for e in db.query(OutreachEntry).filter(
        OutreachEntry.mode == "blog").all()}

    moved = skipped = 0
    for e in old:
        if e.email in existing_blog:
            # Already in blog list — remove the duplicate client copy
            db.delete(e)
            skipped += 1
        else:
            e.mode = "blog"
            existing_blog.add(e.email)
            moved += 1
    db.commit()
    return {"moved": moved, "skipped_duplicates": skipped,
            "message": f"Moved {moved} blog emails to blog dashboard, "
                       f"removed {skipped} duplicates."}


@router.get("/blog/debug")
def blog_debug(site: str = "techbullion.com", time_range: str = "1m"):
    """Diagnostic: test what the engine sees for a given site."""
    from . import blog_research
    from datetime import datetime
    out = {"site": site, "time_range": time_range}
    root = blog_research._root(site)
    out["root"] = root
    base = "https://" + root
    html = blog_research._fetch(base)
    if not html:
        html = blog_research._fetch("http://" + root)
    out["homepage_fetched"] = bool(html)
    out["homepage_size"] = len(html) if html else 0

    # --- Sitemap diagnostics: which sitemap works, how many entries, date impact ---
    delta = blog_research.TIME_RANGES.get(time_range, blog_research.TIME_RANGES["1m"])
    cutoff = datetime.utcnow() - delta
    out["cutoff_date"] = cutoff.strftime("%Y-%m-%d")
    sitemap_urls = ["/post-sitemap.xml", "/post-sitemap1.xml", "/sitemap-posts.xml",
                    "/wp-sitemap-posts-post-1.xml", "/sitemap_index.xml",
                    "/sitemap.xml", "/wp-sitemap.xml", "/news-sitemap.xml"]
    sitemap_report = []
    for sm in sitemap_urls:
        sm_html = blog_research._fetch(base + sm)
        if not sm_html:
            sitemap_report.append({"path": sm, "found": False})
            continue
        entries = blog_research._parse_sitemap_entries(sm_html)
        subs = [u for u, _ in entries if u.endswith(".xml")]
        # How many would survive the date filter?
        dated = with_date = too_old = 0
        for u, mod in entries[:200]:
            d = blog_research._parse_date(mod) or blog_research._date_from_url(u)
            if d:
                with_date += 1
                if d < cutoff:
                    too_old += 1
            dated += 1
        rep = {
            "path": sm, "found": True, "size": len(sm_html),
            "total_entries": len(entries),
            "sub_sitemaps": len(subs), "sample_sub": subs[:2],
            "checked": dated, "had_date": with_date, "dropped_too_old": too_old,
            "sample_dates": [m for _, m in entries[:3]],
        }
        # If parsing found nothing, show what the content actually looks like
        if len(entries) == 0:
            rep["raw_preview"] = sm_html[:400]
            rep["has_loc_tag"] = "<loc" in sm_html.lower()
            rep["has_url_tag"] = "<url" in sm_html.lower()
            rep["looks_like_html"] = ("<!doctype html" in sm_html[:200].lower()
                                      or "<html" in sm_html[:200].lower())
        sitemap_report.append(rep)
        # stop after first working non-index sitemap with real entries
        if entries and not subs:
            break
    out["sitemaps"] = sitemap_report

    try:
        articles = blog_research._find_articles(site, 150, time_range)
        out["articles_found"] = len(articles)
        out["sample_articles"] = articles[:5]
    except Exception as e:
        import traceback
        out["articles_error"] = str(e)
        out["articles_traceback"] = traceback.format_exc()[-500:]
        articles = []
    # Check links in first 3 articles (not just 1)
    total_links = 0
    article_links = []
    for art in articles[:3]:
        art_url = art[0] if isinstance(art, (list, tuple)) else art
        art_date = art[1] if isinstance(art, (list, tuple)) and len(art) > 1 else ""
        try:
            links = blog_research._extract_external_links(art_url)
            total_links += len(links)
            # DEEP DIAGNOSTIC: count raw anchors vs external ones to see where
            # links are being lost (no body container? all internal? filtered?)
            diag = {}
            try:
                from bs4 import BeautifulSoup
                html = blog_research._fetch(art_url)
                if html:
                    diag["html_size"] = len(html)
                    soup = BeautifulSoup(html, "html.parser")
                    all_a = soup.find_all("a", href=True)
                    diag["total_anchors"] = len(all_a)
                    ext = [a for a in all_a if a["href"].startswith("http")
                           and blog_research._root(a["href"]) != blog_research._root(art_url)]
                    diag["external_anchors"] = len(ext)
                    diag["sample_external"] = [a["href"][:60] for a in ext[:5]]
                    # Which body container was detected?
                    import re as _re
                    body = (soup.find("article") or
                            soup.find("div", class_=_re.compile(r"(entry-content|post-content|article-content|article-body|story-body|content)", _re.I)) or
                            soup.find("main"))
                    diag["body_container"] = (body.name + "." + " ".join(body.get("class", []))) if body else "NONE (using whole page)"
            except Exception as de:
                diag["diag_error"] = str(de)
            article_links.append({"article": art_url, "date": art_date,
                                   "links": len(links),
                                   "domains": [l[0] for l in links[:8]],
                                   "diag": diag})
        except Exception as e:
            article_links.append({"article": art_url, "error": str(e)})
    out["total_links_in_first_3"] = total_links
    out["per_article"] = article_links
    return out
