"""Gmail labels for outreach mail.

Puts a coloured label on every message WE send, visible only in the sender's
own Gmail — the recipient never sees it.

  first email   -> "AI Vendor Outreach"  (vendor)
                   "AI Client Hunting"   (client / blog)
  1st follow-up -> the same label + "Follow Up 1"
  2nd follow-up -> "Follow Up 1" is removed and "Follow Up 2" added, etc.

Two backends, because the two sender types differ:
  - oauth senders        -> Gmail API. Creates labels WITH colours.
  - app_password senders -> IMAP (X-GM-LABELS). Labels work; colours cannot be
                            set over IMAP, so pick those once in Gmail's UI.
"""
import imaplib
import json
from datetime import datetime, timedelta

from sqlalchemy import or_, and_

from .database import SessionLocal, Sender
from .crm_models import OutreachEntry
from . import security

# Gmail only accepts colours from its own palette.
LABEL_COLORS = {
    "AI Vendor Outreach": {"backgroundColor": "#ffad47", "textColor": "#ffffff"},  # orange
    "AI Client Hunting":  {"backgroundColor": "#16a766", "textColor": "#ffffff"},  # green
    "Follow Up 1":        {"backgroundColor": "#4a86e8", "textColor": "#ffffff"},  # blue
    "Follow Up 2":        {"backgroundColor": "#a479e2", "textColor": "#ffffff"},  # purple
    "Follow Up 3":        {"backgroundColor": "#f691b3", "textColor": "#ffffff"},  # pink
    "Follow Up 4":        {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"},  # red
    "Blog Research":      {"backgroundColor": "#2da2bb", "textColor": "#ffffff"},  # teal
    "Dealing":            {"backgroundColor": "#ffd6a0", "textColor": "#7a4706"},  # amber
    "Deal Done":          {"backgroundColor": "#16a766", "textColor": "#ffffff"},  # green
}

# Every follow-up label, so a thread that moves on can have them all cleared
ALL_FOLLOWUPS = [f"Follow Up {i}" for i in range(1, 5)]

BASE_LABEL = {
    "vendor": "AI Vendor Outreach",
    "client": "AI Client Hunting",
    "blog":   "Blog Research",       # its own label — these are found via research
}

# Blog mail used to be tagged with the client label. Strip that off when we
# re-label, so nothing ends up carrying both.
OLD_LABELS = {"blog": ["AI Client Hunting"]}


def _stage_of(entry) -> str:
    """Where this conversation has got to."""
    if (getattr(entry, "deal_stage", "") or "").lower() == "done":
        return "done"
    if (entry.status or "") == "replied":
        return "dealing"
    return ""


def labels_for(mode: str, followup_count: int, stage: str = "", category: str = "") -> tuple:
    """(labels to add, labels to remove) for this message.

    A thread moves through stages, and the labels follow it:
        first email            -> base label
        follow-up 1..4         -> base + "Follow Up N"  (previous one removed)
        they replied           -> base + "Dealing"      (follow-ups cleared)
        deal closed            -> base + "Deal Done"    ("Dealing" cleared)

    If a campaign category is given (e.g. "SaaS"), the base label becomes
    "AI SaaS Outreach" so the user can group threads by the category they chose.
    """
    m = (mode or "vendor").lower()
    if category and category.strip():
        base = f"AI {category.strip()} Outreach"
    else:
        base = BASE_LABEL.get(m, BASE_LABEL["vendor"])
    add = [base]
    remove = list(OLD_LABELS.get(m, []))   # clear any label this mode used before
    stage = (stage or "").lower()

    if stage == "done":
        # Deal-status labels are disabled by request. Don't add "Deal Done";
        # just make sure the old status labels are cleared and follow-ups gone.
        remove.append("Deal Done")
        remove.append("Dealing")
        remove.extend(ALL_FOLLOWUPS)
        return add, remove

    if stage == "dealing":
        # They replied. Don't add "Dealing" (disabled); clear follow-up labels
        # and any stale status labels.
        remove.extend(ALL_FOLLOWUPS)
        remove.append("Dealing")
        remove.append("Deal Done")
        return add, remove

    n = int(followup_count or 0)
    if n > 0:
        add.append(f"Follow Up {n}")
        # replace the previous follow-up label so only the latest one shows
        if n > 1:
            remove.append(f"Follow Up {n - 1}")
    return add, remove


# ---------------- Gmail API (OAuth senders) ----------------

def _api_service(creds_dict):
    from googleapiclient.discovery import build
    from .gmail_oauth import credentials_from_dict
    creds = credentials_from_dict(creds_dict)
    return build("gmail", "v1", credentials=creds, cache_discovery=False), creds


def _api_label_ids(service, names):
    """Return {name: id}, creating any label that doesn't exist yet (with colour)."""
    existing = {}
    try:
        for lb in service.users().labels().list(userId="me").execute().get("labels", []):
            existing[lb["name"]] = lb["id"]
    except Exception as e:
        print(f"[Labels] Could not list labels: {e}")
        return {}

    for name in names:
        if name in existing:
            continue
        body = {"name": name, "labelListVisibility": "labelShow",
                "messageListVisibility": "show"}
        if name in LABEL_COLORS:
            body["color"] = LABEL_COLORS[name]
        try:
            created = service.users().labels().create(userId="me", body=body).execute()
            existing[name] = created["id"]
            print(f"[Labels] Created '{name}'")
        except Exception as e:
            print(f"[Labels] Could not create '{name}': {e}")
    return existing


def _find_gmail_id(service, message_id: str):
    """Locate a sent message by its RFC822 Message-ID.

    Needed for mail sent before Gmail's own message id was stored, and as a
    safety net whenever it's missing — otherwise those messages could never
    be labelled.
    """
    if not message_id:
        return None
    try:
        q = "rfc822msgid:" + message_id.strip("<>")
        res = service.users().messages().list(userId="me", q=q, maxResults=1).execute()
        msgs = res.get("messages", [])
        return msgs[0]["id"] if msgs else None
    except Exception:
        return None


def apply_via_api(creds_dict, gmail_id: str, add_names, remove_names, message_id: str = ""):
    """Attach/remove labels on one message using the Gmail API.

    Returns (gmail_id_used, refreshed_creds) on success so the caller can cache
    the id, or (False, None) if there was nothing to change.
    """
    service, creds = _api_service(creds_dict)
    if not gmail_id:
        gmail_id = _find_gmail_id(service, message_id)
        if not gmail_id:
            raise Exception("message not found in this mailbox")
    ids = _api_label_ids(service, list(add_names) + list(remove_names))
    body = {
        "addLabelIds": [ids[n] for n in add_names if n in ids],
        "removeLabelIds": [ids[n] for n in remove_names if n in ids],
    }
    if not body["addLabelIds"] and not body["removeLabelIds"]:
        return False, None
    service.users().messages().modify(userId="me", id=gmail_id, body=body).execute()
    refreshed = {
        "token": creds.token, "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri, "client_id": creds.client_id,
        "client_secret": creds.client_secret, "scopes": list(creds.scopes or []),
    }
    return gmail_id, refreshed


# ---------------- IMAP (app-password senders) ----------------

def _imap_connect(sender_email, app_password):
    m = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    m.login(sender_email, app_password)
    return m


def apply_via_imap(mail, message_id: str, add_names, remove_names) -> bool:
    """Find our sent message by Message-ID and set its Gmail labels."""
    try:
        mail.select('"[Gmail]/Sent Mail"')
        # HEADER search is the reliable way to find the exact message we sent
        _, data = mail.search(None, f'(HEADER Message-ID "{message_id}")')
        nums = data[0].split()
        if not nums:
            return False
        num = nums[-1]
        for name in add_names:
            mail.store(num, "+X-GM-LABELS", f'"{name}"')
        for name in remove_names:
            mail.store(num, "-X-GM-LABELS", f'"{name}"')
        return True
    except Exception as e:
        print(f"[Labels] IMAP label failed for {message_id}: {e}")
        return False


# ---------------- The worker that does it in bulk ----------------

def label_pending(db, limit: int = 300, backfill: bool = False) -> dict:
    """Label every recently-sent message that hasn't been labelled yet.

    Runs in bulk, one connection per sender, so sending itself is never slowed
    down by label calls.
    """
    # Normally only recent mail is worth checking, but after a bulk relabel the
    # whole history needs doing — so age is only used as a filter when there's
    # nothing older already queued.
    q = db.query(OutreachEntry).filter(
        OutreachEntry.message_id != "",
        OutreachEntry.label_state != OutreachEntry.label_target,
    )
    if not backfill:
        cutoff = datetime.utcnow() - timedelta(days=7)
        # A follow-up to an OLD contact is itself a recent message, so look at
        # the most recent activity, not just the first send.
        q = q.filter(or_(
            OutreachEntry.last_followup_at >= cutoff,
            and_(OutreachEntry.last_followup_at.is_(None),
                 OutreachEntry.sent_at >= cutoff),
        ))
    pending = q.order_by(OutreachEntry.sent_at.desc()).limit(limit).all()

    # Nothing recent left to do? Then pick up the older backlog.
    if not pending and not backfill:
        return label_pending(db, limit=limit, backfill=True)

    if not pending:
        return {"labelled": 0, "pending": 0}

    # group by sender so we connect once each
    by_sender = {}
    for e in pending:
        by_sender.setdefault(e.sender_email, []).append(e)

    senders = {s.email: s for s in db.query(Sender).all()}
    done = failed = 0
    skipped_missing = 0      # messages that are simply no longer in the mailbox

    for sender_email, entries in by_sender.items():
        s = senders.get(sender_email)
        if s is None:
            continue

        if s.method == "app_password":
            try:
                pw = security.decrypt(s.app_password) if s.app_password else ""
                if not pw:
                    continue
                mail = _imap_connect(sender_email, pw)
            except Exception as e:
                _sender_errors[sender_email] = f"IMAP login failed: {e}"[:200]
                print(f"[Labels] IMAP connect failed for {sender_email}: {e}")
                continue
            try:
                for e in entries:
                    add, remove = labels_for(e.mode, e.followup_count, _stage_of(e), category=getattr(e, 'category', '') or '')
                    if apply_via_imap(mail, e.message_id, add, remove):
                        e.label_state = e.label_target
                        _sender_errors.pop(sender_email, None)
                        done += 1
                    else:
                        failed += 1
                db.commit()
            finally:
                try:
                    mail.logout()
                except Exception:
                    pass

        elif s.method == "oauth":
            try:
                creds = json.loads(security.decrypt(s.oauth_token)) if s.oauth_token else None
            except Exception:
                creds = None
            if not creds:
                continue
            for e in entries:
                add, remove = labels_for(e.mode, e.followup_count, _stage_of(e), category=getattr(e, 'category', '') or '')
                try:
                    # gmail_id may be blank for older sends — apply_via_api then
                    # finds the message by its Message-ID instead of skipping it.
                    ok, refreshed = apply_via_api(creds, e.gmail_id, add, remove,
                                                  message_id=e.message_id)
                    if ok:
                        e.label_state = e.label_target
                        _sender_errors.pop(sender_email, None)
                        done += 1
                        if isinstance(ok, str):
                            e.gmail_id = ok      # cache it for next time
                        if refreshed:
                            # Saving a refreshed token must never undo a
                            # successful label, so keep it separate.
                            try:
                                s.oauth_token = security.encrypt(json.dumps(refreshed))
                            except Exception:
                                pass
                    else:
                        failed += 1
                except Exception as ex:
                    msg = str(ex)
                    low = msg.lower()

                    # The stored Gmail id no longer resolves (message deleted,
                    # or the id came from an older connection). Drop the stale
                    # id and try once more by Message-ID. If it still can't be
                    # found, stop chasing it — otherwise this retries every 15
                    # seconds forever and floods the log.
                    if "404" in msg or "not found" in low or "notfound" in low:
                        retried = False
                        if e.gmail_id:
                            e.gmail_id = ""
                            try:
                                ok2, ref2 = apply_via_api(creds, "", add, remove,
                                                          message_id=e.message_id)
                                if ok2:
                                    e.label_state = e.label_target
                                    if isinstance(ok2, str):
                                        e.gmail_id = ok2
                                    done += 1
                                    retried = True
                            except Exception:
                                pass
                        if not retried:
                            # Give up on this one, quietly.
                            e.label_state = e.label_target
                            skipped_missing += 1
                        continue

                    failed += 1
                    if "insufficient" in low or "scope" in low:
                        _sender_errors[sender_email] = (
                            "Needs re-authorisation — this Google account was "
                            "connected before labelling was added, so it never "
                            "granted label permission. Remove and re-add it.")
                        print(f"[Labels] {sender_email}: needs re-authorisation "
                              f"(label permission missing)")
                        break
                    _sender_errors[sender_email] = msg[:200]
                    print(f"[Labels] API label failed for {sender_email}: {ex}")
            db.commit()

    if done:
        print(f"[Labels] Labelled {done} message(s).")
    if skipped_missing:
        print(f"[Labels] {skipped_missing} message(s) are no longer in the mailbox "
              f"— skipped so they aren't retried forever.")
    return {"labelled": done, "failed": failed,
            "no_longer_in_mailbox": skipped_missing, "pending": len(pending)}


# ---------------- Background worker ----------------
import threading
import time

_thread = None
_stop = False
# sender email -> last failure reason (surfaced by /crm/labels/status)
_sender_errors = {}
# set by the send engine right after a batch, so labels land almost immediately
_kick = False


def kick():
    """Ask the label worker to run on its next tick (called after sending)."""
    global _kick
    _kick = True


def _loop(interval_seconds: int):
    global _stop, _kick
    while not _stop:
        # Wake early if a send just finished, so labels appear almost at once
        waited = 0
        while waited < interval_seconds:
            if _stop:
                return
            if _kick:
                _kick = False
                break
            time.sleep(1)
            waited += 1
        db = SessionLocal()
        try:
            label_pending(db)
        except Exception as e:
            print(f"[Labels] Worker error: {e}")
        finally:
            db.close()


def start(interval_seconds: int = 15):
    """Apply pending labels continuously (idempotent)."""
    global _thread, _stop
    if _thread is not None and _thread.is_alive():
        return {"status": "already running"}
    _stop = False
    _thread = threading.Thread(target=_loop, args=(interval_seconds,), daemon=True)
    _thread.start()
    print(f"[Labels] Started — applying labels every {interval_seconds}s "
          f"(and immediately after each send).")
    return {"status": "started", "interval_seconds": interval_seconds}


def stop():
    global _stop
    _stop = True
    return {"status": "stopped"}
