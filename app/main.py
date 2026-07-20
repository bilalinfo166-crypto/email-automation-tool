"""Warmwire backend API — connect Gmail senders and send test emails."""
from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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


@app.on_event("startup")
def _startup():
    init_db()
    # Recover interrupted scraper jobs (server crashed/restarted while running)
    try:
        from .database import SessionLocal
        from .crm_models import ScraperJob, ScraperJobDomain
        db = SessionLocal()
        # Find jobs that were "running" when server stopped
        interrupted = db.query(ScraperJob).filter(ScraperJob.status == "running").all()
        for job in interrupted:
            # Reset "scraping" domains back to "pending" so they can be re-processed
            db.query(ScraperJobDomain).filter(
                ScraperJobDomain.job_id == job.id,
                ScraperJobDomain.status == "scraping"
            ).update({"status": "pending"})
            job.status = "stopped"  # user can click Resume
        if interrupted:
            db.commit()
            print(f"Recovered {len(interrupted)} interrupted scraper job(s) — click Resume to continue.")
        db.close()
    except Exception as e:
        print(f"Job recovery warning: {e}")


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


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(t: str, db: Session = Depends(get_db)):
    """Public one-click unsubscribe. Adds the recipient to the suppression list
    so they are never emailed again."""
    item = db.query(QueueItem).filter(QueueItem.unsub_token == t).first()
    if not item:
        return HTMLResponse("<h3>Invalid or expired unsubscribe link.</h3>", status_code=404)
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


@app.get("/")
def root():
    return {"service": "Warmwire API", "docs": "/docs"}
