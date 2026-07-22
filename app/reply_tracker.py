"""Automatic reply detection.

Reads each sender's Gmail inbox and matches incoming senders against the people
we emailed from that account. Anyone who wrote back is marked "replied".

Works for BOTH sender types:
  - app_password senders -> IMAP (imap.gmail.com)
  - oauth senders        -> Gmail API (needs the gmail.readonly scope, which
                            this app already requests)

Unlike open-tracking, this works fine on a local machine: the server connects
OUT to Gmail, so no public URL is needed.
"""
import email
import imaplib
import json
import re
import threading
import time
from datetime import datetime, timedelta

from .database import SessionLocal, Sender
from .crm_models import OutreachEntry, EventLog
from . import security

_thread = None
_stop = False

# Statuses that mean "we emailed this person and they haven't replied yet"
AWAITING = ["sent", "opened"]


def _addr(raw: str) -> str:
    """Pull the bare email address out of a From header."""
    if not raw:
        return ""
    m = re.search(r"[\w\.\-\+%]+@[\w\.\-]+\.\w+", raw)
    return m.group(0).strip().lower() if m else ""


def _inbox_senders_imap(sender_email: str, app_password: str, days: int) -> set:
    """Return the set of addresses that emailed this mailbox recently (IMAP)."""
    found = set()
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(sender_email, app_password)
        mail.select("INBOX")
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'(SINCE {since})')
        ids = data[0].split()
        # Newest first, cap the work
        for num in reversed(ids[-500:]):
            try:
                _, msg_data = mail.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                for part in msg_data:
                    if isinstance(part, tuple):
                        hdr = email.message_from_bytes(part[1])
                        a = _addr(hdr.get("From", ""))
                        if a:
                            found.add(a)
            except Exception:
                continue
        try:
            mail.logout()
        except Exception:
            pass
    except Exception as e:
        print(f"[ReplyTracker] IMAP failed for {sender_email}: {e}")
    return found


def _inbox_senders_oauth(creds_dict: dict, days: int) -> tuple:
    """Return (addresses, refreshed_creds) using the Gmail API."""
    found = set()
    refreshed = None
    try:
        from googleapiclient.discovery import build
        from .gmail_oauth import credentials_from_dict
        creds = credentials_from_dict(creds_dict)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        resp = service.users().messages().list(
            userId="me", q=f"in:inbox newer_than:{days}d", maxResults=200).execute()
        for m in resp.get("messages", []):
            try:
                msg = service.users().messages().get(
                    userId="me", id=m["id"], format="metadata",
                    metadataHeaders=["From"]).execute()
                for h in msg.get("payload", {}).get("headers", []):
                    if h.get("name", "").lower() == "from":
                        a = _addr(h.get("value", ""))
                        if a:
                            found.add(a)
            except Exception:
                continue
        refreshed = {
            "token": creds.token, "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri, "client_id": creds.client_id,
            "client_secret": creds.client_secret, "scopes": list(creds.scopes or []),
        }
    except Exception as e:
        print(f"[ReplyTracker] Gmail API failed: {e}")
    return found, refreshed


def check_replies(db, days: int = 14) -> dict:
    """Scan every sender's inbox and mark anyone who replied.

    Returns a summary dict. Safe to call repeatedly — already-replied entries
    are skipped, so nothing is double-counted.
    """
    senders = db.query(Sender).filter(
        Sender.status.notin_(["auth_failed", "verifying"])).all()

    total_marked = 0
    per_sender = []

    for s in senders:
        # Who are we still waiting on, for THIS sender?
        awaiting = db.query(OutreachEntry).filter(
            OutreachEntry.sender_email == s.email,
            OutreachEntry.status.in_(AWAITING)).all()
        if not awaiting:
            per_sender.append({"sender": s.email, "checked": 0, "replied": 0})
            continue
        waiting_map = {e.email.strip().lower(): e for e in awaiting if e.email}

        # Read the inbox
        if s.method == "app_password" and s.app_password:
            try:
                pw = security.decrypt(s.app_password)
            except Exception:
                pw = ""
            inbox = _inbox_senders_imap(s.email, pw, days) if pw else set()
        elif s.method == "oauth" and s.oauth_token:
            try:
                creds = json.loads(security.decrypt(s.oauth_token))
            except Exception:
                creds = None
            if creds:
                inbox, refreshed = _inbox_senders_oauth(creds, days)
                if refreshed:
                    try:
                        s.oauth_token = security.encrypt(json.dumps(refreshed))
                        db.commit()
                    except Exception:
                        db.rollback()
            else:
                inbox = set()
        else:
            inbox = set()

        # Anyone in both sets replied to us
        marked = 0
        for addr in inbox & set(waiting_map.keys()):
            entry = waiting_map[addr]
            entry.status = "replied"
            entry.replied_at = datetime.utcnow()
            try:
                db.add(EventLog(campaign_id=0, sender_id=s.id, type="replied", contact_id=0))
            except Exception:
                pass
            marked += 1
        if marked:
            try:
                s.replies = (s.replies or 0) + marked
            except Exception:
                pass
            db.commit()
            print(f"[ReplyTracker] {s.email}: {marked} new repl{'y' if marked==1 else 'ies'}")

        total_marked += marked
        per_sender.append({"sender": s.email, "checked": len(awaiting), "replied": marked})

    return {"replies_found": total_marked, "senders": per_sender,
            "checked_at": datetime.utcnow().isoformat()}


def _loop(interval_minutes: int):
    """Background poller."""
    global _stop
    while not _stop:
        # Sleep first so startup isn't slowed down
        for _ in range(interval_minutes * 60):
            if _stop:
                return
            time.sleep(1)
        db = SessionLocal()
        try:
            res = check_replies(db)
            if res["replies_found"]:
                print(f"[ReplyTracker] Found {res['replies_found']} new replies.")
        except Exception as e:
            print(f"[ReplyTracker] Poll error: {e}")
        finally:
            db.close()


def start(interval_minutes: int = 10):
    """Start checking for replies every N minutes (idempotent)."""
    global _thread, _stop
    if _thread is not None and _thread.is_alive():
        return {"status": "already running"}
    _stop = False
    _thread = threading.Thread(target=_loop, args=(interval_minutes,), daemon=True)
    _thread.start()
    print(f"[ReplyTracker] Started — checking every {interval_minutes} min.")
    return {"status": "started", "interval_minutes": interval_minutes}


def stop():
    global _stop
    _stop = True
    return {"status": "stopped"}
