"""Email Send Engine — Final Version.

Features:
- Round-robin senders (4 senders = 1→2→3→4→1→2...)
- Round-robin templates (50 templates rotate)
- Scheduled sending (set time, auto-start)
- Rate control (emails per batch, delay between batches)
- Unsubscribe footer on every email
- Live status updates
"""
import threading
import time
from datetime import datetime, timedelta
from .database import SessionLocal, Sender
from .crm_models import OutreachEntry, EventLog, Campaign
from .gmail_send import send_via_smtp
from .email_templates import get_template, render_template
from . import security

_send_threads = {}


def _get_senders(db, mode):
    """Get all active senders for this mode, ordered by ID."""
    return db.query(Sender).filter(Sender.mode == mode, Sender.warmup == True).order_by(Sender.id).all()


def _build_variables(entry, sender):
    """Build template variables from outreach entry + sender. Site-personalized."""
    email = entry.email
    domain = entry.domain or email.split("@")[-1]
    local = email.split("@")[0]

    # Smart first name extraction
    if "." in local:
        first_name = local.split(".")[0].title()
    elif local in ("info","contact","sales","hello","support","office","admin","help","team","press","media","marketing","editor","hr"):
        first_name = "there"
    else:
        first_name = local.title()

    # Company name from domain
    company = domain.replace("www.","").split(".")[0]
    # Clean company name
    company = company.replace("-"," ").replace("_"," ").title()

    return {
        "first_name": first_name,
        "company_name": company,
        "website": domain,
        "industry": "your industry",
        "sender_name": sender.name or sender.email.split("@")[0].title(),
        "your_company": "Uplyncio",
        "your_website": "uplyncio.com",
        "unsubscribe_url": f"http://127.0.0.1:8000/unsubscribe?email={email}",
    }


def start_campaign_send(campaign_id: int, mode: str, emails_per_batch: int = 10,
                        delay_seconds: int = 60, scheduled_time: str = None):
    """Start sending emails for a campaign. Optionally schedule for later."""
    if campaign_id in _send_threads:
        return {"error": "Campaign already sending"}

    def _run():
        # Wait for scheduled time
        if scheduled_time:
            try:
                target = datetime.fromisoformat(scheduled_time)
                wait = (target - datetime.now()).total_seconds()
                if wait > 0:
                    print(f"[SendEngine] Waiting {wait:.0f}s until {scheduled_time}")
                    time.sleep(wait)
            except:
                pass

        db = SessionLocal()
        try:
            campaign = db.get(Campaign, campaign_id)
            if not campaign:
                return
            campaign.status = "sending"
            db.commit()

            senders = _get_senders(db, mode)
            if not senders:
                campaign.status = "error: no senders"
                db.commit()
                return

            # Get all pending entries for this campaign
            pending = db.query(OutreachEntry).filter(
                OutreachEntry.mode == mode,
                OutreachEntry.status.in_(["pending", "queued"])
            ).order_by(OutreachEntry.id).all()

            sent_count = 0
            template_idx = 0

            for i, entry in enumerate(pending):
                # Check if campaign stopped
                db.refresh(campaign)
                if campaign.status == "stopped":
                    break

                # Round-robin sender
                sender = senders[i % len(senders)]

                # Check daily cap
                if sender.sent_today >= sender.daily_cap:
                    continue  # skip this sender, try next email with next sender

                # Round-robin template
                template = get_template(template_idx)
                template_idx += 1
                variables = _build_variables(entry, sender)
                rendered = render_template(template, variables)

                # Send email
                try:
                    app_pw = security.decrypt(sender.app_password) if sender.app_password else ""
                    if sender.method == "app_password" and app_pw:
                        send_via_smtp(
                            sender_email=sender.email,
                            app_password=app_pw,
                            to_email=entry.email,
                            subject=rendered["subject"],
                            body_html=rendered["body_html"],
                            sender_name=sender.name or ""
                        )
                        # Update status
                        entry.status = "sent"
                        entry.sent_at = datetime.utcnow()
                        entry.sender_email = sender.email
                        entry.subject = rendered["subject"]
                        sender.sent_today += 1
                        sender.total_sent += 1

                        # Log event
                        db.add(EventLog(campaign_id=campaign_id, sender_id=sender.id,
                                       type="sent", contact_id=0))
                        db.commit()
                        sent_count += 1
                        print(f"[SendEngine] Sent #{sent_count}: {entry.email} via {sender.email}")
                    else:
                        entry.status = "failed"
                        db.commit()

                except Exception as e:
                    entry.status = "bounced"
                    db.add(EventLog(campaign_id=campaign_id, sender_id=sender.id,
                                   type="failed", contact_id=0))
                    db.commit()
                    print(f"[SendEngine] Failed: {entry.email} — {e}")

                # Rate control: pause after each batch
                if sent_count > 0 and sent_count % emails_per_batch == 0:
                    print(f"[SendEngine] Batch of {emails_per_batch} done. Waiting {delay_seconds}s...")
                    time.sleep(delay_seconds)

            # Campaign complete
            campaign.status = "completed"
            db.commit()
            print(f"[SendEngine] Campaign #{campaign_id} done. Sent {sent_count} emails.")

        except Exception as e:
            print(f"[SendEngine] Error: {e}")
            try:
                campaign = db.get(Campaign, campaign_id)
                if campaign:
                    campaign.status = "error"
                    db.commit()
            except:
                pass
        finally:
            db.close()
            _send_threads.pop(campaign_id, None)

    t = threading.Thread(target=_run, daemon=True)
    _send_threads[campaign_id] = t
    t.start()
    return {"status": "sending", "campaign_id": campaign_id,
            "scheduled": scheduled_time or "now"}


def stop_campaign(campaign_id: int):
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if campaign:
            campaign.status = "stopped"
            db.commit()
    finally:
        db.close()
    return {"status": "stopped"}
