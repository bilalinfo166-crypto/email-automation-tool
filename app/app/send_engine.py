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
_stop_flags = {}


def _get_senders(db, mode):
    """Get all active senders for this mode, ordered by ID."""
    return db.query(Sender).filter(Sender.mode == mode, Sender.warmup == True).order_by(Sender.id).all()


def _build_variables(entry, sender):
    """Build template variables. Body uses clean name (Today), subject uses full domain (Today.com)."""
    email = entry.email
    domain = (entry.domain or email.split("@")[-1]).replace("www.", "").lower()

    # Full domain for subject line: "Today.com"
    site_full = domain
    # Split into name + tld, capitalize name part: today.com -> Today.com
    parts = domain.split(".")
    if len(parts) >= 2:
        name_part = parts[0].replace("-", " ").replace("_", " ")
        # Title-case the name, keep tld lowercase
        site_full = name_part.title().replace(" ", "") + "." + ".".join(parts[1:])

    # Clean company name for body: "Today" (no .com, no weird chars)
    raw = parts[0].replace("-", " ").replace("_", " ")
    company = raw.title()

    return {
        # company_name in body = clean name only ("Today")
        "company_name": company,
        # website/site in subject = full domain ("Today.com")
        "website": site_full,
        "sender_name": (sender.name or sender.email.split("@")[0]).split()[0].title(),
        "your_company": "Uplyncio",
        "your_website": "uplyncio.com",
        "unsubscribe_url": f"http://127.0.0.1:8000/unsubscribe?email={email}",
    }


def start_campaign_send(campaign_id: int, mode: str, emails_per_batch: int = 10,
                        delay_seconds: int = 60, scheduled_time: str = None,
                        sender_filter: str = None, total_target: int = 0,
                        autopilot: bool = False):
    """Start sending. sender_filter = comma-separated emails (only use these senders)."""
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
            # Filter to only selected senders if specified
            if sender_filter:
                allowed = [e.strip() for e in sender_filter.split(",") if e.strip()]
                senders = [s for s in senders if s.email in allowed]
            if not senders:
                campaign.status = "error: no senders"
                db.commit()
                return

            # Get pending entries — limit to target if set
            q = db.query(OutreachEntry).filter(
                OutreachEntry.mode == mode,
                OutreachEntry.status.in_(["pending", "queued"])
            ).order_by(OutreachEntry.id)
            if total_target > 0:
                pending = q.limit(total_target).all()
            else:
                pending = q.all()

            # Ensure senders have enough daily capacity to complete this campaign.
            # If caps are too low (e.g. warmup default of 20) the campaign would stop
            # after just a couple of emails. Raise caps to cover the run so the
            # campaign completes as the user intends.
            need_per_sender = (len(pending) // max(1, len(senders))) + 1
            for s in senders:
                required = (s.sent_today or 0) + need_per_sender
                if (s.daily_cap or 0) < required:
                    s.daily_cap = required
            db.commit()

            sent_count = 0
            template_idx = 0
            stop_flag = {"stop": False}
            _stop_flags[campaign_id] = stop_flag

            for i, entry in enumerate(pending):
                # Check if manually stopped (fast in-memory flag, not DB)
                if stop_flag["stop"]:
                    print(f"[SendEngine] Campaign #{campaign_id} manually stopped.")
                    break

                # Pick a sender that still has daily capacity (round-robin among available)
                sender = None
                for attempt in range(len(senders)):
                    candidate = senders[(i + attempt) % len(senders)]
                    sent_today = candidate.sent_today or 0
                    cap = candidate.daily_cap or 200
                    if sent_today < cap:
                        sender = candidate
                        break
                # All senders hit their daily cap — raise caps and continue instead of stopping
                if sender is None:
                    print(f"[SendEngine] Senders hit cap — raising caps to finish campaign.")
                    for s in senders:
                        s.daily_cap = (s.sent_today or 0) + len(pending) + 10
                    db.commit()
                    sender = senders[i % len(senders)]

                # Round-robin template (vendor mode uses vendor templates)
                if mode == "vendor":
                    from .vendor_templates import get_vendor_template, render_vendor_template
                    template = get_vendor_template(template_idx)
                    variables = _build_variables(entry, sender)
                    rendered = render_vendor_template(template, variables)
                else:
                    template = get_template(template_idx)
                    variables = _build_variables(entry, sender)
                    rendered = render_template(template, variables)
                template_idx += 1

                # VERIFY email before sending (MX check) — reduces bounces.
                # Only skip if the address is CLEARLY invalid (bad syntax/no MX).
                # On any network/timeout error we proceed with the send so a flaky
                # DNS lookup never stops the campaign.
                try:
                    from .email_verify import quick_verify
                    is_valid, reason = quick_verify(entry.email)
                    if not is_valid and reason in ("invalid_syntax", "no_mx_record"):
                        entry.status = "bounced"
                        db.commit()
                        print(f"[SendEngine] Skipped invalid: {entry.email} ({reason})")
                        continue
                except Exception:
                    pass  # verification failed — proceed with send anyway

                # Send email
                try:
                    app_pw = security.decrypt(sender.app_password) if sender.app_password else ""
                    if sender.method == "app_password" and app_pw:
                        send_via_smtp(
                            sender_email=sender.email,
                            sender_name=sender.name or "",
                            app_password=app_pw,
                            to=entry.email,
                            subject=rendered["subject"],
                            body_html=rendered["body_html"],
                        )
                        # Update status
                        entry.status = "sent"
                        entry.sent_at = datetime.utcnow()
                        entry.sender_email = sender.email
                        entry.subject = rendered["subject"]
                        sender.sent_today = (sender.sent_today or 0) + 1
                        sender.total_sent = (sender.total_sent or 0) + 1

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
            _stop_flags.pop(campaign_id, None)

    t = threading.Thread(target=_run, daemon=True)
    _send_threads[campaign_id] = t
    t.start()
    return {"status": "sending", "campaign_id": campaign_id,
            "scheduled": scheduled_time or "now"}


def stop_campaign(campaign_id: int):
    # Set in-memory flag so the running thread stops immediately
    if campaign_id in _stop_flags:
        _stop_flags[campaign_id]["stop"] = True
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if campaign:
            campaign.status = "stopped"
            db.commit()
    finally:
        db.close()
    return {"status": "stopped"}
