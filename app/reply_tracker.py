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

# Company-level matching is skipped for these — otherwise any stranger with a
# gmail address would be counted as a reply.
FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.in",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
    "gmx.com", "gmx.de", "mail.com", "zoho.com", "yandex.com", "yandex.ru",
    "rediffmail.com", "qq.com", "163.com", "126.com", "naver.com",
}


MSGID_RE = re.compile(r"<[^<>\s]+>")

BOUNCE_SENDERS = ("mailer-daemon@", "postmaster@", "noreply-dmarc", "bounce@")
BOUNCE_SUBJECTS = ("delivery status notification", "undeliverable", "delivery failure",
                   "returned mail", "mail delivery failed", "address not found")
AUTO_SUBJECTS = ("out of office", "automatic reply", "auto-reply", "autoreply",
                 "away from my desk", "on vacation", "thank you for contacting")


def _gmail_body(message) -> str:
    """Readable text out of a Gmail API message payload."""
    import base64

    def _walk(part):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime in ("text/plain", "text/html"):
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")[:8000]
            except Exception:
                return ""
        for sub in part.get("parts", []) or []:
            got = _walk(sub)
            if got:
                return got
        return ""

    try:
        return _walk(message.get("payload", {}) or {})
    except Exception:
        return ""


def _plain_text(msg) -> str:
    """Readable text of an email, preferring the plain-text part."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8",
                                              errors="replace")[:8000]
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8",
                                              errors="replace")[:8000]
            return ""
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8",
                                  errors="replace")[:8000]
    except Exception:
        pass
    return ""


def _referenced_ids(hdr) -> set:
    """Message-IDs this incoming email is answering (In-Reply-To + References)."""
    ids = set()
    for h in ("In-Reply-To", "References"):
        v = hdr.get(h, "") or ""
        for m in MSGID_RE.findall(v):
            ids.add(m.strip())
    return ids


def _failed_recipients(subject: str, body: str) -> set:
    """Addresses a bounce notice reports as undeliverable.

    Delivery failures always name the address that couldn't be reached, so this
    catches them even when the notice doesn't quote our original Message-ID.
    Our own senders are filtered out — a bounce is addressed TO us.
    """
    found = set()
    text = f"{subject or ''} {body or ''}"
    for m in re.finditer(r"[\w.\-+]+@[\w.\-]+\.\w+", text):
        a = m.group(0).strip().lower().strip(".,;:>)")
        if not a or a.startswith(("mailer-daemon", "postmaster", "noreply", "no-reply")):
            continue
        if a.endswith(("googlemail.com", "google.com")) and "daemon" in a:
            continue
        found.add(a)
    return found


def _is_bounce(from_addr: str, subject: str) -> bool:
    f = (from_addr or "").lower()
    sub = (subject or "").lower()
    return (any(b in f for b in BOUNCE_SENDERS)
            or any(b in sub for b in BOUNCE_SUBJECTS))


def _is_auto_reply(subject: str) -> bool:
    sub = (subject or "").lower()
    return any(a in sub for a in AUTO_SUBJECTS)


def _addr(raw: str) -> str:
    """Pull the bare email address out of a From header."""
    if not raw:
        return ""
    m = re.search(r"[\w\.\-\+%]+@[\w\.\-]+\.\w+", raw)
    return m.group(0).strip().lower() if m else ""


def _inbox_senders_imap(sender_email: str, app_password: str, days: int):
    """Return (replied_to_ids, bounced_ids) for this mailbox.

    A message only counts as a REPLY if its In-Reply-To / References header
    points at a Message-ID we actually sent. Matching on the From address alone
    was wrong: newsletters and marketing mail from the same company look
    identical to a reply, which produced dozens of false "replied" rows.

    Scans INBOX **and Spam** — replies from people who've never emailed you
    before very often get filed as spam, so inbox-only misses real replies.

    Headers are fetched in ONE bulk command per folder. Fetching them one message
    at a time meant hundreds of round-trips per mailbox, which made the whole
    check take hours (or appear to hang).
    """
    replied_to, bounced, reply_from = set(), set(), set()
    bounced_addrs = set()   # addresses a bounce notice says are undeliverable
    threads = {}            # message-id / sender -> every message of that conversation
    mail = None
    try:
        # Hard timeout so one unresponsive mailbox can't stall everything
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
        mail.login(sender_email, app_password)
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")

        for folder in ('INBOX', '"[Gmail]/Spam"'):
            try:
                mail.select(folder, readonly=True)
                _, data = mail.search(None, f'(SINCE {since})')
                ids = data[0].split()
                if not ids:
                    continue
                recent = ids[-300:]          # newest 300
                id_set = b",".join(recent)
                # Headers AND the message text — the body is what carries the
                # price, link counts and turnaround time for the deals sheet.
                _, msg_data = mail.fetch(id_set, "(BODY.PEEK[])")
                for part in msg_data:
                    if isinstance(part, tuple) and part[1]:
                        try:
                            hdr = email.message_from_bytes(part[1])
                            body_text = _plain_text(hdr)
                            refs = _referenced_ids(hdr)
                            frm = _addr(hdr.get("From", ""))
                            subj = hdr.get("Subject", "") or ""
                            looks_like_reply = bool(refs) or subj.lower().lstrip().startswith("re:")
                            if not looks_like_reply:
                                continue          # newsletter / cold mail, not a reply
                            if _is_bounce(frm, subj):
                                bounced |= refs
                                # A bounce always names the address that failed.
                                # Reading it means we catch bounces even when
                                # the notice doesn't quote our Message-ID.
                                for a in _failed_recipients(subj, body_text):
                                    bounced_addrs.add(a)
                                continue
                            if _is_auto_reply(subj):
                                continue
                            replied_to |= refs
                            # Fallback for mail we sent before Message-IDs were
                            # recorded: remember WHO replied, so those older
                            # rows can still be matched by address.
                            if frm:
                                reply_from.add(frm)
                            if body_text:
                                # Keep every message of the conversation, in the
                                # order it arrived — a deal is negotiated across
                                # several emails, not settled in the first one.
                                stamp = hdr.get("Date", "") or ""
                                for key in list(refs) + ([frm] if frm else []):
                                    threads.setdefault(key, []).append(
                                        (stamp, frm, body_text))
                        except Exception:
                            continue
                print(f"[ReplyTracker] {sender_email}: read {len(recent)} from {folder}")
            except Exception as fe:
                print(f"[ReplyTracker] {sender_email}: could not read {folder}: {fe}")
                continue
    except Exception as e:
        print(f"[ReplyTracker] IMAP failed for {sender_email}: {type(e).__name__}: {e}")
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
    return replied_to, bounced, reply_from, threads, bounced_addrs


def _inbox_senders_oauth(creds_dict: dict, days: int) -> tuple:
    """Return ((replied_to_ids, bounced_ids), refreshed_creds) via the Gmail API.

    Same rule as IMAP: only messages that reference one of OUR Message-IDs count.
    """
    replied_to, bounced, reply_from = set(), set(), set()
    bounced_addrs = set()
    threads = {}
    refreshed = None
    try:
        from googleapiclient.discovery import build
        from .gmail_oauth import credentials_from_dict
        creds = credentials_from_dict(creds_dict)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        resp = service.users().messages().list(
            userId="me", q=f"(in:inbox OR in:spam) newer_than:{days}d",
            maxResults=200).execute()
        msgs = resp.get("messages", [])

        def _collect(request_id, response, exception):
            if exception is not None or not response:
                return
            hdrs = {}
            for h in response.get("payload", {}).get("headers", []):
                hdrs[h.get("name", "").lower()] = h.get("value", "")
            body_text = _gmail_body(response)
            refs = set()
            for key in ("in-reply-to", "references"):
                for m in MSGID_RE.findall(hdrs.get(key, "")):
                    refs.add(m.strip())
            frm = _addr(hdrs.get("from", ""))
            subj = hdrs.get("subject", "") or ""
            looks_like_reply = bool(refs) or subj.lower().lstrip().startswith("re:")
            if not looks_like_reply:
                return
            if _is_bounce(frm, subj):
                bounced.update(refs)
                for a in _failed_recipients(subj, body_text):
                    bounced_addrs.add(a)
                return
            if _is_auto_reply(subj):
                return
            replied_to.update(refs)
            if frm:
                reply_from.add(frm)
            if body_text:
                stamp = hdrs.get("date", "")
                for key in list(refs) + ([frm] if frm else []):
                    threads.setdefault(key, []).append((stamp, frm, body_text))

        for i in range(0, len(msgs), 100):
            batch = service.new_batch_http_request(callback=_collect)
            for m in msgs[i:i + 100]:
                batch.add(service.users().messages().get(
                    userId="me", id=m["id"],
                    format="full"))
            batch.execute()

        print(f"[ReplyTracker] Gmail API: read {len(msgs)} messages")
        refreshed = {
            "token": creds.token, "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri, "client_id": creds.client_id,
            "client_secret": creds.client_secret, "scopes": list(creds.scopes or []),
        }
    except Exception as e:
        print(f"[ReplyTracker] Gmail API failed: {type(e).__name__}: {e}")
    return (replied_to, bounced, reply_from, threads, bounced_addrs), refreshed


def check_replies(db, days: int = 14, progress: dict = None) -> dict:
    """Scan every sender's inbox and mark anyone who replied.

    Returns a summary dict. Safe to call repeatedly — already-replied entries
    are skipped, so nothing is double-counted.
    """
    senders = db.query(Sender).filter(
        Sender.status.notin_(["auth_failed", "verifying"])).all()

    total_marked = 0
    per_sender = []

    for idx, s in enumerate(senders, 1):
        if progress is not None:
            progress["current"] = f"{idx}/{len(senders)} — {s.email}"
        print(f"[ReplyTracker] ({idx}/{len(senders)}) checking {s.email}...")

        # People we emailed from THIS sender who haven't answered yet.
        # Keyed by the Message-ID we sent them — that's what a genuine reply
        # points back at.
        awaiting = db.query(OutreachEntry).filter(
            OutreachEntry.sender_email == s.email,
            OutreachEntry.status.in_(AWAITING),
        ).all()
        # Even with nothing new awaiting a reply, the mailbox is still read —
        # ongoing negotiations need their latest messages so the deals sheet
        # keeps up with the conversation.
        has_deals = db.query(OutreachEntry).filter(
            OutreachEntry.sender_email == s.email,
            OutreachEntry.status == "replied").count()
        if not awaiting and not has_deals:
            per_sender.append({"sender": s.email, "checked": 0, "replied": 0})
            continue
        # Newer mail is matched exactly, by the Message-ID we sent.
        by_msgid = {e.message_id: e for e in awaiting if e.message_id}
        # Older mail (sent before Message-IDs were recorded) can only be matched
        # by address — still safe, because we only look at incoming mail that is
        # genuinely a reply, never at newsletters or cold mail.
        by_addr = {e.email.strip().lower(): e for e in awaiting
                   if not e.message_id and e.email}

        # Read the mailbox
        replied_ids, bounced_ids, reply_from, threads = set(), set(), set(), {}
        bounced_addrs = set()
        if s.method == "app_password" and s.app_password:
            try:
                pw = security.decrypt(s.app_password)
            except Exception:
                pw = ""
            if pw:
                (replied_ids, bounced_ids, reply_from, threads,
                 bounced_addrs) = _inbox_senders_imap(s.email, pw, days)
        elif s.method == "oauth" and s.oauth_token:
            try:
                creds = json.loads(security.decrypt(s.oauth_token))
            except Exception:
                creds = None
            if creds:
                ((replied_ids, bounced_ids, reply_from, threads,
                  bounced_addrs), refreshed) = _inbox_senders_oauth(creds, days)
                if refreshed:
                    try:
                        s.oauth_token = security.encrypt(json.dumps(refreshed))
                        db.commit()
                    except Exception:
                        db.rollback()

        marked = 0
        # Real replies: the incoming mail quoted the exact message we sent
        for mid in replied_ids & set(by_msgid.keys()):
            entry = by_msgid[mid]
            if entry.status == "replied":
                continue
            entry.status = "replied"
            entry.replied_at = datetime.utcnow()
            # Move the Gmail label on: this thread is now a conversation.
            entry.label_target = f"{entry.mode}:dealing"
            entry.label_state = ""
            try:
                db.add(EventLog(campaign_id=0, sender_id=s.id, type="replied", contact_id=0))
            except Exception:
                pass
            _record_deal(db, entry, threads.get(mid) or threads.get(addr_of(entry)) or [])
            marked += 1

        # Older rows: the person we emailed sent us a genuine reply
        for addr in reply_from & set(by_addr.keys()):
            entry = by_addr[addr]
            if entry.status == "replied":
                continue
            entry.status = "replied"
            entry.replied_at = datetime.utcnow()
            entry.label_target = f"{entry.mode}:dealing"
            entry.label_state = ""
            try:
                db.add(EventLog(campaign_id=0, sender_id=s.id, type="replied", contact_id=0))
            except Exception:
                pass
            _record_deal(db, entry, threads.get(addr) or [])
            marked += 1

        # Addresses a delivery failure named — mark them so they're never
        # emailed or reminded again.
        if bounced_addrs:
            hit = db.query(OutreachEntry).filter(
                OutreachEntry.sender_email == s.email,
                OutreachEntry.email.in_(list(bounced_addrs)),
                OutreachEntry.status.in_(["sent", "opened", "pending", "queued"]),
            ).all()
            for e in hit:
                e.status = "bounced"
            if hit:
                print(f"[ReplyTracker] {s.email}: {len(hit)} address(es) reported "
                      f"undeliverable — they won't be emailed again")

        # Bounce notifications reference our message too — record them properly
        # instead of counting them as interest.
        for mid in bounced_ids & set(by_msgid.keys()):
            entry = by_msgid[mid]
            if entry.status not in ("replied", "bounced"):
                entry.status = "bounced"

        # Anyone already marked as replied should have a deal row too — not just
        # the ones detected in this pass. Their conversation is re-read each
        # time, so prices stay current as the negotiation moves on.
        try:
            already = db.query(OutreachEntry).filter(
                OutreachEntry.sender_email == s.email,
                OutreachEntry.status == "replied").all()
            for e in already:
                convo = (threads.get(e.message_id) if e.message_id else None) \
                        or threads.get(addr_of(e)) or []
                _record_deal(db, e, convo)
        except Exception as de:
            print(f"[ReplyTracker] deal sync warning for {s.email}: {de}")

        if marked:
            try:
                s.replies = (s.replies or 0) + marked
            except Exception:
                pass
        db.commit()
        if marked:
            print(f"[ReplyTracker] {s.email}: {marked} new repl{'y' if marked==1 else 'ies'}")

        if marked:
            try:
                from . import gmail_labels
                gmail_labels.kick()
            except Exception:
                pass
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


# ---- One-off check that runs in the background ----
# Reading several mailboxes can take minutes, which is longer than an HTTP
# request should wait. So the endpoint kicks this off and returns immediately;
# the result is stored here and fetched via /crm/replies/status.
_last_result = {"state": "never run"}
_check_thread = None


def _run_once():
    global _last_result
    _last_result = {"state": "running", "started_at": datetime.utcnow().isoformat(),
                    "current": "starting..."}
    db = SessionLocal()
    try:
        res = check_replies(db, progress=_last_result)
        res["state"] = "done"
        _last_result = res
        print(f"[ReplyTracker] Manual check done — {res['replies_found']} replies found.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        _last_result = {"state": "error", "error": str(e)}
    finally:
        db.close()


def reset_replies(db, mode: str = "") -> dict:
    """Undo reply marks that were made by the old, unreliable matching.

    The previous version counted ANY mail from that address (or even that
    company) as a reply, so newsletters and marketing mail were logged as
    replies. This puts those rows back to "sent" so the next check can decide
    properly using Message-ID matching.
    """
    q = db.query(OutreachEntry).filter(OutreachEntry.status == "replied")
    if mode:
        q = q.filter(OutreachEntry.mode == mode)
    rows = q.all()
    n = 0
    for e in rows:
        e.status = "sent"
        e.replied_at = None
        n += 1
    # sender reply counters were inflated the same way
    for snd in db.query(Sender).all():
        snd.replies = 0
    db.commit()
    print(f"[ReplyTracker] Reset {n} unverified reply mark(s).")
    return {"reset": n,
            "note": "These are back to 'sent'. Run a reply check to re-detect "
                    "genuine replies (matched by Message-ID)."}


def check_now():
    """Kick off a one-off check in the background. Returns immediately."""
    global _check_thread
    if _check_thread is not None and _check_thread.is_alive():
        return {"state": "already running",
                "note": "A check is already in progress — see /crm/replies/status"}
    _check_thread = threading.Thread(target=_run_once, daemon=True)
    _check_thread.start()
    return {"state": "started",
            "note": "Checking inboxes in the background. "
                    "Call /crm/replies/status in a minute to see the result."}


def last_result():
    running = bool(_check_thread is not None and _check_thread.is_alive())
    out = dict(_last_result)
    out["in_progress"] = running
    out["auto_poller_running"] = bool(_thread is not None and _thread.is_alive())
    return out


def addr_of(entry) -> str:
    return (entry.email or "").strip().lower()


def _record_deal(db, entry, conversation=None):
    """Create or update the deal row from the WHOLE conversation.

    A price is rarely settled in the first email — they quote, we push back,
    they agree a different number. So every message is read in order and later
    answers replace earlier ones. The last thing they said is what stands.
    """
    from .crm_models import Deal
    from . import deal_parser

    email = addr_of(entry)
    if not email:
        return
    deal = db.query(Deal).filter(Deal.vendor_email == email,
                                 Deal.mode == entry.mode).first()
    now = datetime.utcnow()
    if deal is None:
        deal = Deal(mode=entry.mode, vendor_email=email,
                    our_email=entry.sender_email or "",
                    primary_site=(entry.domain or "").replace("www.", ""),
                    sites=(entry.domain or "").replace("www.", ""),
                    first_reply_at=now, status="dealing")
        db.add(deal)
    deal.last_reply_at = now
    if not deal.our_email:
        deal.our_email = entry.sender_email or ""

    messages = conversation or []
    if not messages:
        try:
            db.commit()
        except Exception:
            db.rollback()
        return

    # Oldest first, so the newest message has the final say
    def _when(m):
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(m[0]) or datetime.min
        except Exception:
            return datetime.min
    try:
        messages = sorted(messages, key=_when)
    except Exception:
        pass

    FIELDS = ("currency", "guest_post_price", "link_insert_price",
              "dofollow_links", "nofollow_links", "tat", "sheet_url", "sample_url")
    agreed = {}
    all_domains = []
    closed = False

    for _stamp, _frm, text in messages:
        if not text:
            continue
        try:
            info = deal_parser.parse_reply(text, exclude_domains=[deal.primary_site])
        except Exception:
            continue
        for f in FIELDS:
            val = info.get(f) or ""
            if val:
                agreed[f] = val          # later message wins
        for d in info.get("domains") or []:
            if d not in all_domains:
                all_domains.append(d)
        if info.get("looks_done"):
            closed = True

    for f, val in agreed.items():
        setattr(deal, f, val)

    if all_domains:
        have = [d for d in (deal.sites or "").split(",") if d]
        for d in all_domains:
            if d not in have:
                have.append(d)
        primary = deal.primary_site
        if primary and primary in have:
            have.remove(primary)
            have.insert(0, primary)
        deal.sites = ",".join(have[:60])

    # Keep the conversation itself, so the numbers can always be checked
    try:
        deal.notes = "\n\n---\n\n".join(
            (t or "")[:1500] for _s, _f, t in messages[-6:])[:8000]
    except Exception:
        pass

    if closed and deal.status != "done":
        deal.status = "done"
        deal.deal_date = now
        entry.deal_stage = "done"
        entry.label_target = f"{entry.mode}:done"
        entry.label_state = ""

    try:
        db.commit()
    except Exception:
        db.rollback()
