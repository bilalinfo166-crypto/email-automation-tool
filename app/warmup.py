"""Inbox warmup engine.

Honest scope: warmup here means sending a small, gradually-increasing number of
plain emails BETWEEN THE USER'S OWN CONNECTED INBOXES (owned mailboxes only).
It builds sending history/reputation on those accounts. It does NOT fabricate
engagement with third parties and never emails anyone the user doesn't own.
You need at least two connected senders for warmup to run.
"""
from datetime import date, datetime
from sqlalchemy.orm import Session

from .database import Sender
from . import gmail_send as sender_lib
from . import gmail_oauth as oauth
from . import security

WARMUP_START = 5     # emails/day on day 0
WARMUP_STEP = 5      # +5 per day
WARMUP_MAX = 40      # cap per inbox per day
WARMED_HEALTH = 90   # health at which a sender is considered "warmed"


def _day_of(sender: Sender) -> int:
    base = sender.created_at.date() if sender.created_at else date.today()
    return max(0, (date.today() - base).days)


def _target_today(sender: Sender) -> int:
    return min(WARMUP_START + _day_of(sender) * WARMUP_STEP, WARMUP_MAX)


def _reset_daily(s: Sender):
    if s.last_send_date != date.today():
        s.sent_today = 0
        s.warmup_sent_today = 0
        s.last_send_date = date.today()


def warmup_status(db: Session) -> dict:
    senders = db.query(Sender).all()
    rows = []
    for s in senders:
        _reset_daily(s)
        s.warmup_day = _day_of(s)
        rows.append({
            "email": s.email,
            "warmup_on": s.warmup,
            "day": s.warmup_day,
            "target_today": _target_today(s),
            "sent_today": s.warmup_sent_today,
            "health": s.health,
            "status": s.status,
        })
    db.commit()
    owned = len(senders)
    return {"senders": rows, "connected_inboxes": owned,
            "can_warm": owned >= 2,
            "note": "Warmup sends only between your own connected inboxes." if owned >= 2
                    else "Connect at least two inboxes to run warmup."}


def _send_one(db: Session, frm: Sender, to: Sender) -> bool:
    subject = "WarmWire warmup"
    html = "<p>Warmup message between your connected inboxes to build sending reputation.</p>"
    try:
        if frm.method == "oauth":
            creds = oauth.creds_from_json(security.decrypt(frm.oauth_token))
            res = sender_lib.send_via_oauth(creds, frm.email, frm.name or "WarmWire",
                                            to.email, subject, html)
            frm.oauth_token = security.encrypt(oauth.creds_to_json(res["creds"]))
        else:
            app_pw = security.decrypt(frm.app_password)
            sender_lib.send_via_smtp(frm.email, frm.name or "WarmWire", app_pw,
                                     to.email, subject, html)
        return True
    except Exception:
        return False


def run_warmup(db: Session, max_sends: int = 10) -> dict:
    """Send up to `max_sends` warmup emails between owned inboxes, respecting each
    inbox's gradual daily target. Call periodically (e.g. a few times a day)."""
    senders = [s for s in db.query(Sender).all() if s.warmup]
    if len(senders) < 2:
        return {"sent": 0, "skipped": 0, "reason": "Need at least two connected inboxes with warmup on."}

    for s in senders:
        _reset_daily(s)

    sent = skipped = 0
    n = len(senders)
    ri = 0
    for frm in senders:
        if sent >= max_sends:
            break
        target = _target_today(frm)
        while frm.warmup_sent_today < target and sent < max_sends:
            # pick a different owned inbox as the recipient (round-robin)
            to = senders[ri % n]
            ri += 1
            if to.id == frm.id:
                to = senders[ri % n]
                ri += 1
            if to.id == frm.id:
                break
            if _send_one(db, frm, to):
                frm.warmup_sent_today += 1
                # health climbs gradually as history builds
                frm.health = min(100, frm.health + 1)
                if frm.health >= WARMED_HEALTH:
                    frm.status = "warmed"
                sent += 1
            else:
                skipped += 1
                break
        db.commit()

    return {"sent": sent, "skipped": skipped, "inboxes": n}
