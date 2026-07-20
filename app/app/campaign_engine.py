"""Turns a campaign into a rate-limited, compliant send.

Pipeline: build queue (dedup + suppression) -> round-robin sender assignment ->
send in batches respecting per-sender daily caps -> log every event.
Every send re-checks suppression and injects the required footer.
"""
from datetime import date, datetime
from sqlalchemy.orm import Session

from .database import Sender
from .crm_models import Campaign, Contact, QueueItem, EventLog
from . import compliance, gmail_send as sender_lib
from . import gmail_oauth as oauth
from . import security
from .config import settings


def _base_url() -> str:
    # Where the public /unsubscribe endpoint lives.
    return settings.OAUTH_REDIRECT_URI.split("/auth/")[0]


def build_queue(db: Session, campaign_id: int) -> dict:
    """Create queue items for all eligible contacts. Skips suppressed + already-queued (dedup)."""
    c = db.get(Campaign, campaign_id)
    if not c:
        raise ValueError("Campaign not found")

    senders = db.query(Sender).all()
    if not senders:
        raise ValueError("No senders connected. Add at least one sender first.")

    already = {q.contact_id for q in db.query(QueueItem).filter(QueueItem.campaign_id == campaign_id)}
    contacts = db.query(Contact).all()

    added = skipped_supp = skipped_dupe = 0
    rr = 0
    for ct in contacts:
        if ct.id in already:
            skipped_dupe += 1
            continue
        if compliance.is_suppressed(db, ct.email):
            skipped_supp += 1
            continue
        sender = senders[rr % len(senders)]  # round-robin: load balancing only
        rr += 1
        db.add(QueueItem(
            campaign_id=campaign_id,
            contact_id=ct.id,
            sender_id=sender.id,
            status="queued",
            unsub_token=compliance.new_unsub_token(),
        ))
        added += 1
    db.commit()
    return {"queued": added, "skipped_suppressed": skipped_supp, "skipped_duplicate": skipped_dupe}


def _reset_daily(s: Sender):
    if s.last_send_date != date.today():
        s.sent_today = 0
        s.last_send_date = date.today()


def send_batch(db: Session, campaign_id: int, batch_size: int = 20) -> dict:
    """Send up to `batch_size` messages, respecting per-sender daily caps.
    Call repeatedly (or from a scheduler) to work through the queue with pacing."""
    c = db.get(Campaign, campaign_id)
    if not c:
        raise ValueError("Campaign not found")

    compliance.assert_sendable(db, c)      # hard gate: profile + fields + lawful basis + approved
    if c.status == "approved":
        c.status = "sending"
        db.commit()

    items = (db.query(QueueItem)
             .filter(QueueItem.campaign_id == campaign_id, QueueItem.status == "queued")
             .limit(batch_size * 3).all())

    sent = failed = skipped = 0
    processed = 0
    for item in items:
        if processed >= batch_size:
            break
        contact = db.get(Contact, item.contact_id)
        sender = db.get(Sender, item.sender_id)
        if not contact or not sender:
            item.status = "skipped"; item.error = "missing contact/sender"; skipped += 1
            continue

        # re-check suppression at send time
        if compliance.is_suppressed(db, contact.email):
            item.status = "skipped"; item.error = "suppressed"; skipped += 1
            continue

        _reset_daily(sender)
        if sender.sent_today >= min(sender.daily_cap, c.per_sender_daily_cap):
            continue  # this sender is capped for today; leave item queued for later

        unsubscribe_link = f"{_base_url()}/unsubscribe?t={item.unsub_token}"
        html = compliance.compose_email(db, c, unsubscribe_link)

        try:
            if sender.method == "oauth":
                creds = oauth.creds_from_json(security.decrypt(sender.oauth_token))
                res = sender_lib.send_via_oauth(creds, sender.email, c.from_name or sender.name,
                                                contact.email, c.subject, html)
                sender.oauth_token = security.encrypt(oauth.creds_to_json(res["creds"]))
            else:
                app_pw = security.decrypt(sender.app_password)
                sender_lib.send_via_smtp(sender.email, c.from_name or sender.name, app_pw,
                                         contact.email, c.subject, html)
            item.status = "sent"; item.sent_at = datetime.utcnow()
            sender.sent_today += 1; sender.total_sent += 1
            contact.status = "sent"
            db.add(EventLog(campaign_id=campaign_id, contact_id=contact.id,
                            sender_id=sender.id, type="sent"))
            sent += 1
        except Exception as e:
            item.status = "failed"; item.error = str(e)[:200]
            sender.failed += 1
            db.add(EventLog(campaign_id=campaign_id, contact_id=contact.id,
                            sender_id=sender.id, type="failed", meta=str(e)[:120]))
            failed += 1
        processed += 1
        db.commit()

    remaining = (db.query(QueueItem)
                 .filter(QueueItem.campaign_id == campaign_id, QueueItem.status == "queued").count())
    if remaining == 0:
        c.status = "completed"; db.commit()

    return {"sent": sent, "failed": failed, "skipped": skipped, "remaining": remaining,
            "min_delay_sec": c.min_delay_sec, "max_delay_sec": c.max_delay_sec}


def analytics(db: Session, campaign_id: int | None = None) -> dict:
    q = db.query(EventLog)
    if campaign_id:
        q = q.filter(EventLog.campaign_id == campaign_id)
    counts = {"sent": 0, "opened": 0, "replied": 0, "failed": 0,
              "unsubscribed": 0, "not_interested": 0}
    for ev in q.all():
        if ev.type in counts:
            counts[ev.type] += 1
    return counts
