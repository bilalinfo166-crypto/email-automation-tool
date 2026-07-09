"""Reply handling.

scan_replies: reads recent inbox messages from each OAuth-connected sender,
matches them to known contacts, logs a 'replied' event, and — if the wording
means opt-out — adds the contact to the suppression list and marks their status
as 'Unsubscribed' or 'Not Interested'.

Note: reading replies uses the gmail.readonly scope (already granted at connect).
App-password senders can't be read via API here — use apply_reply() manually
(POST /crm/replies/manual) for those, or forward opt-outs into the app.
"""
import base64
import re
from sqlalchemy.orm import Session
from googleapiclient.discovery import build

from .database import Sender
from .crm_models import Contact, QueueItem, EventLog
from . import compliance, security
from . import gmail_oauth as oauth

FROM_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _decode_body(payload) -> str:
    text = ""
    if payload.get("body", {}).get("data"):
        try:
            text += base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
        except Exception:
            pass
    for part in payload.get("parts", []) or []:
        text += _decode_body(part)
    return text


def apply_reply(db: Session, contact: Contact, campaign_id: int, sender_id: int, text: str) -> str:
    """Log the reply and act on opt-out wording. Returns the resulting status."""
    db.add(EventLog(campaign_id=campaign_id, contact_id=contact.id,
                    sender_id=sender_id, type="replied"))
    decision = compliance.classify_optout(text)
    if decision == "unsubscribe":
        compliance.add_suppression(db, contact.email, reason="unsubscribe")
        contact.status = "unsubscribed"
        db.add(EventLog(campaign_id=campaign_id, contact_id=contact.id,
                        sender_id=sender_id, type="unsubscribed"))
    elif decision == "not_interested":
        compliance.add_suppression(db, contact.email, reason="not_interested")
        contact.status = "not_interested"
        db.add(EventLog(campaign_id=campaign_id, contact_id=contact.id,
                        sender_id=sender_id, type="not_interested"))
    else:
        contact.status = "replied"
    db.commit()
    return contact.status


def _campaign_for(db: Session, contact_id: int) -> int:
    q = (db.query(QueueItem)
         .filter(QueueItem.contact_id == contact_id)
         .order_by(QueueItem.id.desc()).first())
    return q.campaign_id if q else 0


def scan_replies(db: Session, lookback: str = "newer_than:14d", max_msgs: int = 100) -> dict:
    """Scan OAuth senders' inboxes for replies from known contacts."""
    contacts = {c.email.lower(): c for c in db.query(Contact).all()}
    replied = optouts = 0

    for sender in db.query(Sender).filter(Sender.method == "oauth").all():
        try:
            creds = oauth.credentials_from_dict(oauth.creds_from_json(security.decrypt(sender.oauth_token)))
            service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            listing = service.users().messages().list(
                userId="me", q=f"in:inbox {lookback}", maxResults=max_msgs).execute()
            for meta in listing.get("messages", []):
                msg = service.users().messages().get(userId="me", id=meta["id"], format="full").execute()
                headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
                from_addr = ""
                m = FROM_RE.search(headers.get("from", ""))
                if m:
                    from_addr = m.group(0).lower()
                contact = contacts.get(from_addr)
                if not contact:
                    continue
                body = headers.get("subject", "") + " " + _decode_body(msg["payload"])
                status = apply_reply(db, contact, _campaign_for(db, contact.id), sender.id, body)
                replied += 1
                if status in ("unsubscribed", "not_interested"):
                    optouts += 1
        except Exception:
            continue

    return {"replies_processed": replied, "opt_outs": optouts}
