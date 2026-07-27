"""Warmwire backend API — connect Gmail senders and send test emails."""
from datetime import date, datetime
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session
from googleapiclient.discovery import build

from .config import settings
from .database import init_db, get_db, Sender
from . import schemas, security
from . import gmail_oauth as oauth
from . import gmail_send as sender_lib
from . import compliance
from .crm_models import QueueItem, Contact, EventLog
from .crm_routes import router as crm_router
from .scraper_routes import router as scraper_router

app = FastAPI(title="Warmwire API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crm_router)
app.include_router(scraper_router)


@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
def serve_app():
    """Serve the WarmWire UI from the backend so it runs on http://127.0.0.1:8000
    instead of file://. Modern browsers block file:// pages from calling
    http://127.0.0.1 (treated as a cross-origin/insecure request), which makes
    the dashboard load blank. Serving from the same origin fixes that."""
    import os
    # Look for warmwire.html next to the app folder (the deploy location)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in [
        os.path.join(here, "warmwire.html"),
        os.path.join(os.path.dirname(here), "warmwire.html"),
        "warmwire.html",
    ]:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return HTMLResponse(f.read())
    return HTMLResponse(
        "<h2>warmwire.html not found</h2><p>Place warmwire.html next to the "
        "app folder (in C:\\Users\\Dell\\Desktop\\files\\) and reload.</p>",
        status_code=404)


@app.on_event("startup")
def _startup():
    init_db()
    # ---- AUTO-RESUME after a crash / PC shutdown ----
    # Anything that was mid-flight when the server died is picked up again
    # automatically, so no scraping progress or pending emails are lost.
    try:
        from .database import SessionLocal
        from .crm_models import ScraperJob, ScraperJobDomain, Campaign
        from . import scraper_jobs
        db = SessionLocal()

        # 1) Scraper jobs that were "running" when the server stopped
        interrupted = db.query(ScraperJob).filter(ScraperJob.status == "running").all()
        for job in interrupted:
            # Domains caught mid-scrape go back to "pending" so they aren't lost.
            # Guarded per job — a lock on one must not abort the whole recovery.
            try:
                db.query(ScraperJobDomain).filter(
                    ScraperJobDomain.job_id == job.id,
                    ScraperJobDomain.status == "scraping"
                ).update({"status": "pending"}, synchronize_session=False)
                db.commit()
            except Exception as je:
                db.rollback()
                print(f"[AutoResume] Could not requeue job #{job.id}: {je}")

        for job in interrupted:
            try:
                remaining = db.query(ScraperJobDomain).filter(
                    ScraperJobDomain.job_id == job.id,
                    ScraperJobDomain.status == "pending").count()
                if remaining == 0:
                    job.status = "completed"
                    db.commit()
                    print(f"[AutoResume] Scraper job #{job.id} had nothing left — marked completed.")
                else:
                    # Queue them all; only ONE runs at a time so scraping never
                    # saturates the machine and freezes the dashboard.
                    job.status = "queued"
                    db.commit()
                    print(f"[AutoResume] Scraper job #{job.id} ({job.name}): "
                          f"{remaining} domains left — queued.")
            except Exception as je:
                db.rollback()
                print(f"[AutoResume] Could not queue job #{job.id}: {je}")

        # Interrupted jobs are queued, NOT started. Auto-starting them meant
        # every restart immediately launched a few-thousand-domain scrape with
        # 35 workers before the dashboard had loaded once — so the app was busy
        # from the first second and nothing else got a turn. Press Resume in the
        # Email Scraper panel (or set AUTO_RESUME_SCRAPER=1) to pick it back up.
        import os
        if os.getenv("AUTO_RESUME_SCRAPER", "").strip() in ("1", "true", "yes"):
            try:
                scraper_jobs._start_next_queued()
            except Exception as se:
                print(f"[AutoResume] Could not start queued job: {se}")
        else:
            print("[AutoResume] Queued job(s) are waiting — press Resume in the "
                  "Email Scraper panel to continue them.")

        # 2) Campaigns that were "sending" when the server stopped
        try:
            from . import send_engine
            from .crm_models import OutreachEntry

            # Entries caught mid-send go back to "pending" (they were claimed but
            # never completed). Without this they'd be stuck forever.
            try:
                db.query(OutreachEntry).filter(
                    OutreachEntry.status == "sending"
                ).update({"status": "pending"}, synchronize_session=False)
                db.commit()
            except Exception:
                db.rollback()

            live_camps = db.query(Campaign).filter(Campaign.status == "sending").all()
            # Pending emails are selected by MODE, so only ONE campaign per mode
            # may run — otherwise every email would be sent twice.
            newest_per_mode = {}
            for camp in live_camps:
                cur = newest_per_mode.get(camp.mode)
                if cur is None or camp.id > cur.id:
                    newest_per_mode[camp.mode] = camp
            for camp in live_camps:
                if newest_per_mode.get(camp.mode) is not camp:
                    camp.status = "stopped"      # older duplicates stay stopped
                    db.commit()
                    print(f"[AutoResume] Campaign #{camp.id} paused "
                          f"(another campaign already covers '{camp.mode}').")

            for mode_name, camp in newest_per_mode.items():
                pending = db.query(OutreachEntry).filter(
                    OutreachEntry.mode == camp.mode,
                    OutreachEntry.status.in_(["pending", "queued"])).count()
                if pending > 0:
                    print(f"[AutoResume] Campaign #{camp.id} ({camp.name}): "
                          f"{pending} emails pending — resuming automatically.")
                    send_engine.start_campaign_send(
                        campaign_id=camp.id, mode=camp.mode,
                        emails_per_batch=camp.emails_per_batch or 10,
                        delay_seconds=camp.delay_seconds or 30,
                        min_delay=camp.min_delay_sec or 15,
                        max_delay=camp.max_delay_sec or 40,
                        sender_filter=camp.sender_emails or "",
                        total_target=camp.total_target or 0,
                        autopilot=bool(camp.autopilot),
                    )
                else:
                    camp.status = "completed"
                    db.commit()
                    print(f"[AutoResume] Campaign #{camp.id} had no pending emails — completed.")
        except Exception as ce:
            print(f"[AutoResume] Campaign resume warning: {ce}")

        db.close()
    except Exception as e:
        print(f"[AutoResume] Recovery warning: {e}")

    # ---- Automatic reply tracking ----
    # Polls each sender's inbox and marks anyone who wrote back. This works on a
    # local machine because the server connects OUT to Gmail (no public URL needed).
    try:
        from . import reply_tracker
        reply_tracker.start(interval_minutes=10)
    except Exception as e:
        print(f"[ReplyTracker] Could not start: {e}")

    # ---- Gmail labelling ----
    # Tags every message we send with a coloured label in the SENDER's Gmail.
    try:
        from . import gmail_labels
        gmail_labels.start(interval_seconds=15)
    except Exception as e:
        print(f"[Labels] Could not start: {e}")

    # ---- Follow-up reminders ----
    # Anyone who hasn't replied after 30 hours gets a short nudge. Sent in
    # batches each hour rather than all at once, so a backlog never goes out
    # as one blast.
    try:
        from . import followup_engine
        followup_engine.start(interval_minutes=60, delay_hours=30,
                              max_followups=2, per_sender=8)
    except Exception as e:
        print(f"[FollowUp] Could not start: {e}")


def _reset_daily(s: Sender):
    if s.last_send_date != date.today():
        s.sent_today = 0
        s.last_send_date = date.today()


# ---------------- Senders ----------------

@app.get("/senders", response_model=list[schemas.SenderOut])
def list_senders(mode: str = "", db: Session = Depends(get_db)):
    q = db.query(Sender)
    if mode:
        q = q.filter(Sender.mode == mode)
    return q.order_by(Sender.created_at.desc()).all()


@app.get("/senders/{sender_id}", response_model=schemas.SenderOut)
def get_sender(sender_id: int, db: Session = Depends(get_db)):
    s = db.get(Sender, sender_id)
    if not s:
        raise HTTPException(404, "Sender not found")
    return s


@app.delete("/senders/{sender_id}")
def delete_sender(sender_id: int, db: Session = Depends(get_db)):
    s = db.get(Sender, sender_id)
    if not s:
        raise HTTPException(404, "Sender not found")
    db.delete(s)
    db.commit()
    return {"deleted": sender_id}


@app.put("/senders/{sender_id}")
def update_sender(sender_id: int, data: dict, db: Session = Depends(get_db)):
    s = db.get(Sender, sender_id)
    if not s:
        raise HTTPException(404, "Sender not found")
    if "name" in data:
        s.name = data["name"]
    if "daily_cap" in data:
        s.daily_cap = max(1, min(1000, int(data["daily_cap"])))
    if "warmup" in data:
        s.warmup = bool(data["warmup"])
    db.commit()
    db.refresh(s)
    return {"id": s.id, "email": s.email, "name": s.name, "daily_cap": s.daily_cap, "warmup": s.warmup}


@app.post("/senders/app-password", response_model=schemas.SenderOut)
def add_app_password_sender(data: schemas.AppPasswordSenderIn, db: Session = Depends(get_db)):
    if db.query(Sender).filter(Sender.email == data.email).first():
        raise HTTPException(400, "That email is already connected.")

    # Save INSTANTLY — no blocking SMTP check. Verification happens in the
    # background so the Add button responds immediately.
    s = Sender(
        email=data.email,
        name=data.name or data.email.split("@")[0].title(),
        mode=getattr(data, 'mode', 'vendor') or 'vendor',
        method="app_password",
        app_password=security.encrypt(data.app_password),
        daily_cap=20 if data.warmup else data.daily_cap,
        warmup=data.warmup,
        status="verifying",
        health=32 if data.warmup else 70,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    # Verify Gmail login in the background (non-blocking)
    import threading
    sender_id = s.id
    plain_pw = data.app_password
    email_addr = data.email
    is_warmup = data.warmup

    def _verify_bg():
        import smtplib
        from .database import SessionLocal
        ok = False
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
                server.ehlo(); server.starttls()
                server.login(email_addr, plain_pw)
            ok = True
        except Exception as e:
            print(f"[Sender] Verify failed for {email_addr}: {e}")
        bg = SessionLocal()
        try:
            snd = bg.get(Sender, sender_id)
            if snd:
                if ok:
                    snd.status = "warming" if is_warmup else "warmed"
                else:
                    snd.status = "auth_failed"
                bg.commit()
        finally:
            bg.close()

    threading.Thread(target=_verify_bg, daemon=True).start()
    return s


# ---------------- Google OAuth ----------------

@app.get("/auth/google/start")
def google_start():
    """Returns the Google consent URL. Open it in the browser."""
    url, state = oauth.get_authorization_url()
    return {"authorization_url": url, "state": state}


@app.get("/auth/google/callback", response_class=HTMLResponse)
def google_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    """Google redirects here after the user clicks Allow."""
    try:
        creds_dict = oauth.exchange_code(code, state=state)
    except Exception as e:
        return HTMLResponse(f"<h3>Auth failed:</h3><pre>{e}</pre>", status_code=400)

    # Ask Google which mailbox was actually granted (strict — email comes from Google)
    creds = oauth.credentials_from_dict(creds_dict)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    email = profile["emailAddress"].lower()

    if settings.SENDING_DOMAIN and not email.endswith("@" + settings.SENDING_DOMAIN):
        return HTMLResponse(
            f"<h3>{email} is not on {settings.SENDING_DOMAIN}.</h3>"
            "<p>Please connect a mailbox on your sending domain.</p>",
            status_code=400,
        )

    existing = db.query(Sender).filter(Sender.email == email).first()
    token_json = oauth.creds_to_json(creds_dict)
    if existing:
        existing.oauth_token = security.encrypt(token_json)
        existing.method = "oauth"
    else:
        db.add(Sender(
            email=email,
            name=email.split("@")[0].title(),
            method="oauth",
            oauth_token=security.encrypt(token_json),
            daily_cap=20,
            warmup=True,
            status="warming",
            health=32,
        ))
    db.commit()
    return HTMLResponse(
        f"<h2>✅ Connected {email}</h2>"
        "<p>You can close this tab and go back to Warmwire.</p>"
    )


# ---------------- Sending ----------------

@app.post("/senders/{sender_id}/send-test")
def send_test(sender_id: int, data: schemas.TestEmailIn, db: Session = Depends(get_db)):
    s = db.get(Sender, sender_id)
    if not s:
        raise HTTPException(404, "Sender not found")

    _reset_daily(s)
    if s.sent_today >= s.daily_cap:
        raise HTTPException(429, f"Daily cap reached ({s.daily_cap}). Try again tomorrow.")

    try:
        if s.method == "oauth":
            creds_dict = oauth.creds_from_json(security.decrypt(s.oauth_token))
            result = sender_lib.send_via_oauth(
                creds_dict, s.email, s.name, data.to, data.subject, data.body_html
            )
            # save any refreshed token
            s.oauth_token = security.encrypt(oauth.creds_to_json(result["creds"]))
        else:
            app_pw = security.decrypt(s.app_password)
            result = sender_lib.send_via_smtp(
                s.email, s.name, app_pw, data.to, data.subject, data.body_html
            )
    except Exception as e:
        s.failed += 1
        db.commit()
        raise HTTPException(400, f"Send failed: {e}")

    s.sent_today += 1
    s.total_sent += 1
    db.commit()
    return {"ok": True, "message_id": result.get("id"), "sent_today": s.sent_today}


# ---------------- Open Tracking ----------------

# 1x1 transparent GIF (43 bytes) — returned for every tracking-pixel hit
_PIXEL_GIF = bytes([
    0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00,
    0x00, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x21, 0xF9, 0x04, 0x01, 0x00,
    0x00, 0x00, 0x00, 0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
    0x00, 0x02, 0x02, 0x44, 0x01, 0x00, 0x3B
])


@app.get("/track/open")
def track_open(t: str, db: Session = Depends(get_db)):
    """Invisible tracking pixel. When a recipient opens the email, their client
    loads this image, letting us mark the email as 'opened'. Always returns a
    1x1 transparent GIF so the email renders normally either way."""
    from .crm_models import OutreachEntry
    try:
        entry = db.query(OutreachEntry).filter(OutreachEntry.unsub_token == t).first()
        # Only upgrade status forward: pending/sent -> opened. Never downgrade
        # replied/unsubscribed/bounced back to opened.
        if entry and entry.status in ("sent", "pending"):
            entry.status = "opened"
            entry.opened_at = datetime.utcnow()
            db.add(EventLog(campaign_id=0, contact_id=0, sender_id=0,
                            type="opened", meta=entry.email))
            db.commit()
            print(f"[Track] Opened: {entry.email}")
        elif entry and entry.status in ("opened", "replied") and not entry.opened_at:
            # Record first-open time if we somehow missed it
            entry.opened_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        print(f"[Track] Open tracking error: {e}")
    # Cache headers off so every open is counted, not served from cache
    return Response(content=_PIXEL_GIF, media_type="image/gif",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                             "Pragma": "no-cache", "Expires": "0"})


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(t: str, db: Session = Depends(get_db)):
    """Public one-click unsubscribe. Adds the recipient to the suppression list
    so they are never emailed again. Handles BOTH old QueueItem tokens AND
    new OutreachEntry tokens (from send_engine)."""
    from .crm_models import OutreachEntry

    # 1) Try old system: QueueItem token (campaign_engine)
    item = db.query(QueueItem).filter(QueueItem.unsub_token == t).first()
    if item:
        contact = db.get(Contact, item.contact_id)
        if contact:
            compliance.add_suppression(db, contact.email, reason="unsubscribe")
            db.add(EventLog(campaign_id=item.campaign_id, contact_id=contact.id,
                            sender_id=item.sender_id, type="unsubscribed"))
            db.commit()
        return HTMLResponse(
            "<h2>You have been unsubscribed.</h2>"
            "<p>You will not receive any further emails from us. Sorry for the intrusion.</p>"
        )

    # 2) Try new system: OutreachEntry token (send_engine)
    entry = db.query(OutreachEntry).filter(OutreachEntry.unsub_token == t).first()
    if entry:
        compliance.add_suppression(db, entry.email, reason="unsubscribe")
        entry.status = "unsubscribed"
        db.add(EventLog(campaign_id=0, contact_id=0,
                        sender_id=0, type="unsubscribed",
                        meta=entry.email))
        db.commit()
        return HTMLResponse(
            "<h2>You have been unsubscribed.</h2>"
            "<p>You will not receive any further emails from us. Sorry for the intrusion.</p>"
        )

    return HTMLResponse("<h3>Invalid or expired unsubscribe link.</h3>", status_code=404)


@app.get("/")
def root():
    return {"service": "Warmwire API", "docs": "/docs"}
