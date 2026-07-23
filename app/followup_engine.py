"""Follow-up reminders.

If someone we emailed hasn't replied after N hours, send them ONE short,
polite reminder. Up to MAX_FOLLOWUPS reminders, spaced out.

Safety rules baked in (these matter — follow-ups to people who never asked to
hear from you is exactly how domains get burned):
  - never follow up someone who replied, bounced, or unsubscribed
  - never follow up an address on the suppression list
  - always reuse the ORIGINAL sender, so the thread stays consistent
  - subject becomes "Re: <original>" so it reads like a normal nudge
  - respects each sender's daily cap
  - every reminder still carries a working unsubscribe link
"""
import json
import random
import threading
import time
import uuid
from datetime import datetime, timedelta

from .database import SessionLocal, Sender
from .crm_models import OutreachEntry, EventLog
from .gmail_send import send_via_smtp, send_via_oauth
from .config import settings
from . import security, compliance

_thread = None
_stop = False

# Defaults — overridable per run
DEFAULT_DELAY_HOURS = 24     # wait this long after the last message
MAX_FOLLOWUPS = 2            # never nag more than this
SECOND_FOLLOWUP_DAYS = 3     # extra wait before the 2nd reminder

# Follow-ups must match the ORIGINAL pitch of that dashboard:
#   vendor -> we asked THEM about buying a paid guest post on their site
#   client -> we offered THEM our guest-posting service
# Sending the wrong one (offering our service to a site we wanted to buy from,
# or asking a prospect for their rates) would be confusing and unprofessional.
FOLLOWUP_BODIES = {
    "vendor": [
        "Hi,<br><br>Just following up on my note about a paid guest post on {company}.<br><br>"
        "If you do accept them, could you share your rate, turnaround time, and whether the "
        "links are dofollow? If you're not taking guest posts right now, just say so and I'll "
        "close the loop.<br><br>Thanks,<br>{sender_name}",

        "Hi,<br><br>Circling back on my earlier email about placing a sponsored post on "
        "{company}.<br><br>A quick reply with your pricing would be great — and if it's not "
        "something you offer, no problem at all.<br><br>Best,<br>{sender_name}",

        "Hi,<br><br>Quick nudge in case my message about a guest post on {company} got buried.<br><br>"
        "Happy to work to your guidelines — I just need your rate and turnaround. "
        "A \"no thanks\" is a perfectly good answer too.<br><br>Thanks,<br>{sender_name}",
    ],
    "client": [
        "Hi,<br><br>Following up on my note about backlinks for {company}.<br><br>"
        "If getting placements on high-authority sites in your niche is something you're "
        "exploring, I'm happy to send over a few examples of what we've done. If it's not a "
        "priority right now, just let me know.<br><br>Thanks,<br>{sender_name}",

        "Hi,<br><br>Just bringing my earlier email back up in case it got lost.<br><br>"
        "I can share a short list of sites we could realistically place {company} on, plus "
        "pricing — no obligation. And if this isn't a fit, a quick \"not interested\" is "
        "completely fine.<br><br>Best,<br>{sender_name}",

        "Hi,<br><br>Quick nudge on my message about guest posts for {company}.<br><br>"
        "If rankings aren't where you'd like them, this is usually the gap. Happy to walk you "
        "through what we'd suggest — or to stop reaching out if you'd prefer.<br><br>"
        "Thanks,<br>{sender_name}",
    ],
}
# Blog research pitches the same service as the client dashboard
FOLLOWUP_BODIES["blog"] = FOLLOWUP_BODIES["client"]


def _company_name(entry) -> str:
    """Clean company name from the domain: 'today-news.com' -> 'Today News'."""
    domain = (entry.domain or (entry.email or "").split("@")[-1] or "")
    domain = domain.replace("www.", "").lower()
    first = domain.split(".")[0] if domain else ""
    return first.replace("-", " ").replace("_", " ").title() or "your site"

FOOTER = (
    '<br><br><div style="border-top:1px solid #e5e7eb;margin-top:18px;padding-top:10px;'
    'color:#6b7280;font-size:11px">'
    '<a href="{unsub}" style="color:#6b7280;font-size:11px">Unsubscribe</a></div>'
)


def find_due(db, mode: str = "", delay_hours: int = DEFAULT_DELAY_HOURS,
             max_followups: int = MAX_FOLLOWUPS, limit: int = 500):
    """Contacts who are due a reminder right now."""
    now = datetime.utcnow()
    q = db.query(OutreachEntry).filter(
        # Only people we actually emailed and who never wrote back.
        # "replied", "bounced" and "unsubscribed" are excluded by this filter.
        OutreachEntry.status.in_(["sent", "opened"]),
        OutreachEntry.sent_at.isnot(None),
        OutreachEntry.followup_count < max_followups,
    )
    if mode:
        q = q.filter(OutreachEntry.mode == mode)

    due = []
    for e in q.order_by(OutreachEntry.sent_at).limit(limit * 4).all():
        # How long since the last thing we sent them?
        last = e.last_followup_at or e.sent_at
        if not last:
            continue
        # 1st reminder after delay_hours; later ones get more breathing room
        wait = timedelta(hours=delay_hours)
        if (e.followup_count or 0) >= 1:
            wait = timedelta(days=SECOND_FOLLOWUP_DAYS)
        if now - last < wait:
            continue
        if not e.sender_email:
            continue                      # we don't know who sent it — skip
        if compliance.is_suppressed(db, e.email):
            continue                      # unsubscribed — never nag
        due.append(e)
        if len(due) >= limit:
            break
    return due


def _send_one(db, entry, sender, senders_sent_today):
    """Send a single reminder. Returns True if it went out."""
    # Respect the sender's daily cap
    cap = sender.daily_cap or 150
    if senders_sent_today.get(sender.email, 0) >= cap:
        return False

    token = entry.unsub_token or uuid.uuid4().hex
    entry.unsub_token = token
    unsub = f"{settings.PUBLIC_URL}/unsubscribe?t={token}"

    # Pick the wording for THIS contact's dashboard (vendor vs client vs blog),
    # so a site we wanted to buy from never receives our sales pitch, and a
    # prospect never gets asked for their guest-post rates.
    entry_mode = (entry.mode or "vendor").lower()
    bodies = FOLLOWUP_BODIES.get(entry_mode) or FOLLOWUP_BODIES["vendor"]
    body = random.choice(bodies).format(
        sender_name=sender.name or "",
        company=_company_name(entry),
    )
    body_html = body + FOOTER.format(unsub=unsub)

    base_subject = entry.subject or "Quick follow-up"
    subject = base_subject if base_subject.lower().startswith("re:") else f"Re: {base_subject}"

    if sender.method == "app_password":
        pw = security.decrypt(sender.app_password) if sender.app_password else ""
        if not pw:
            return False
        res = send_via_smtp(sender_email=sender.email, sender_name=sender.name or "",
                            app_password=pw, to=entry.email, subject=subject,
                            body_html=body_html)
        entry.message_id = res.get("message_id", "")
    elif sender.method == "oauth":
        raw = security.decrypt(sender.oauth_token) if sender.oauth_token else ""
        if not raw:
            return False
        result = send_via_oauth(creds_dict=json.loads(raw), sender_email=sender.email,
                                sender_name=sender.name or "", to=entry.email,
                                subject=subject, body_html=body_html)
        if result.get("creds"):
            sender.oauth_token = security.encrypt(json.dumps(result["creds"]))
        entry.message_id = result.get("message_id", "")
        entry.gmail_id = result.get("gmail_id", "")
    else:
        return False

    entry.followup_count = (entry.followup_count or 0) + 1
    entry.last_followup_at = datetime.utcnow()
    # Label worker will swap "Follow Up N-1" for "Follow Up N"
    entry.label_target = f"{entry.mode}:{entry.followup_count}"
    entry.label_state = ""
    try:
        from . import gmail_labels
        gmail_labels.kick()      # apply the new "Follow Up N" label right away
    except Exception:
        pass
    sender.sent_today = (sender.sent_today or 0) + 1
    sender.total_sent = (sender.total_sent or 0) + 1
    senders_sent_today[sender.email] = senders_sent_today.get(sender.email, 0) + 1
    try:
        db.add(EventLog(campaign_id=0, sender_id=sender.id, type="followup", contact_id=0))
    except Exception:
        pass
    return True


def run_followups(db, mode: str = "", delay_hours: int = DEFAULT_DELAY_HOURS,
                  max_followups: int = MAX_FOLLOWUPS, limit: int = 200,
                  min_gap_sec: int = 20, dry_run: bool = False) -> dict:
    """Send reminders to everyone who's due. Set dry_run=True to preview only."""
    due = find_due(db, mode=mode, delay_hours=delay_hours,
                   max_followups=max_followups, limit=limit)
    if dry_run:
        return {"due": len(due), "sent": 0, "dry_run": True,
                "preview": [{"email": e.email, "sent_at": e.sent_at.isoformat() if e.sent_at else "",
                             "followups_so_far": e.followup_count or 0} for e in due[:20]]}

    # Look up senders once
    sender_map = {s.email: s for s in db.query(Sender).filter(
        Sender.status.notin_(["auth_failed", "verifying"])).all()}
    sent_today = {e: (s.sent_today or 0) for e, s in sender_map.items()}

    sent = skipped = failed = 0
    last_by_sender = {}

    for entry in due:
        sender = sender_map.get(entry.sender_email)
        if sender is None:
            skipped += 1
            continue

        # Pace per sender, same idea as the main send engine
        prev = last_by_sender.get(sender.email)
        if prev is not None:
            wait = min_gap_sec - (time.time() - prev)
            if wait > 0:
                time.sleep(wait)

        try:
            if _send_one(db, entry, sender, sent_today):
                db.commit()
                sent += 1
                last_by_sender[sender.email] = time.time()
                print(f"[FollowUp] Reminder #{entry.followup_count} -> {entry.email} "
                      f"via {sender.email}")
            else:
                skipped += 1
        except Exception as e:
            db.rollback()
            failed += 1
            print(f"[FollowUp] Failed {entry.email}: {e}")

    return {"due": len(due), "sent": sent, "skipped": skipped, "failed": failed}


def send_test(db, to_email: str, mode: str = "vendor", sender_email: str = "",
              company: str = "") -> dict:
    """Send ONE sample follow-up to your own address so you can see the wording.

    Touches no real data: no OutreachEntry is created or updated, no counters
    move. Purely a preview of what a live reminder would look like.
    """
    to_email = (to_email or "").strip().lower()
    if "@" not in to_email:
        return {"sent": False, "error": "Give a valid email, e.g. ?email=you@gmail.com"}

    q = db.query(Sender).filter(Sender.status.notin_(["auth_failed", "verifying"]))
    sender = q.filter(Sender.email == sender_email).first() if sender_email else q.first()
    if sender is None:
        return {"sent": False, "error": "No usable sender found."}

    mode = (mode or "vendor").lower()
    bodies = FOLLOWUP_BODIES.get(mode) or FOLLOWUP_BODIES["vendor"]
    company_name = company or (to_email.split("@")[-1].split(".")[0].title())

    body = random.choice(bodies).format(sender_name=sender.name or "",
                                        company=company_name)
    unsub = f"{settings.PUBLIC_URL}/unsubscribe?t=test"
    body_html = body + FOOTER.format(unsub=unsub)
    subject = f"Re: [TEST] {mode} follow-up preview"

    try:
        if sender.method == "app_password":
            pw = security.decrypt(sender.app_password) if sender.app_password else ""
            if not pw:
                return {"sent": False, "error": f"{sender.email} has no app password stored."}
            send_via_smtp(sender_email=sender.email, sender_name=sender.name or "",
                          app_password=pw, to=to_email, subject=subject,
                          body_html=body_html)
        elif sender.method == "oauth":
            raw = security.decrypt(sender.oauth_token) if sender.oauth_token else ""
            if not raw:
                return {"sent": False, "error": f"{sender.email} has no OAuth token stored."}
            res = send_via_oauth(creds_dict=json.loads(raw), sender_email=sender.email,
                                 sender_name=sender.name or "", to=to_email,
                                 subject=subject, body_html=body_html)
            if res.get("creds"):
                sender.oauth_token = security.encrypt(json.dumps(res["creds"]))
                db.commit()
        else:
            return {"sent": False, "error": f"Unknown sender method: {sender.method}"}
    except Exception as e:
        return {"sent": False, "error": f"{type(e).__name__}: {e}"}

    print(f"[FollowUp] TEST {mode} follow-up -> {to_email} via {sender.email}")
    return {"sent": True, "to": to_email, "mode": mode, "from": sender.email,
            "subject": subject, "company_used": company_name,
            "note": "Nothing in your real send list was changed."}


def _loop(interval_minutes: int, delay_hours: int, max_followups: int):
    global _stop
    while not _stop:
        for _ in range(interval_minutes * 60):
            if _stop:
                return
            time.sleep(1)
        db = SessionLocal()
        try:
            res = run_followups(db, delay_hours=delay_hours, max_followups=max_followups)
            if res["sent"]:
                print(f"[FollowUp] Sent {res['sent']} reminder(s).")
        except Exception as e:
            print(f"[FollowUp] Poll error: {e}")
        finally:
            db.close()


def start(interval_minutes: int = 60, delay_hours: int = DEFAULT_DELAY_HOURS,
          max_followups: int = MAX_FOLLOWUPS):
    """Start the automatic follow-up sender (idempotent)."""
    global _thread, _stop
    if _thread is not None and _thread.is_alive():
        return {"status": "already running"}
    _stop = False
    _thread = threading.Thread(target=_loop,
                               args=(interval_minutes, delay_hours, max_followups),
                               daemon=True)
    _thread.start()
    print(f"[FollowUp] Started — checking hourly, reminder after {delay_hours}h, "
          f"max {max_followups} per contact.")
    return {"status": "started", "delay_hours": delay_hours,
            "max_followups": max_followups}


def stop():
    global _stop
    _stop = True
    return {"status": "stopped"}
