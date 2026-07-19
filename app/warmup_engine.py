"""Real-time Cross-User Email Warmup Engine (Pool-based).

KEY IDEA: Warmup works best when DIFFERENT domains email each other.
- We build a shared POOL of all warmup-enabled senders across ALL users
- Sender A (userX@domain1.com) emails Sender B (userY@domain2.com)
- We NEVER pair two senders from the SAME domain (Gmail detects that)
- More users join → bigger pool → better, more natural warmup

Each warmup email has "WU" in subject. Receiver: rescues from spam,
marks important, reads, replies — building real sender reputation.
"""
import imaplib
import smtplib
import email
import email.utils
import random
import time
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .database import SessionLocal, Sender
from . import security

_warmup_thread = None
_warmup_running = False

WARMUP_SUBJECTS = [
    "WU · Quick catch up", "WU · Following up", "WU · Project update",
    "WU · Notes from today", "WU · Re: last week", "WU · Quick question",
    "WU · Thanks for the update", "WU · Meeting recap", "WU · Next steps",
    "WU · Checking in", "WU · Re: proposal", "WU · Weekly sync",
    "WU · Draft for review", "WU · Some feedback", "WU · Friendly reminder",
    "WU · Great work", "WU · Let's connect", "WU · Update inside",
]

WARMUP_BODIES = [
    "Hi,\n\nJust following up on what we discussed. Everything looks good — let me know if you need anything else.\n\nBest",
    "Hey,\n\nThanks for sending that over. I've reviewed it and it all makes sense. Talk soon.\n\nCheers",
    "Hello,\n\nQuick update — things are moving nicely. I'll share more later this week.\n\nRegards",
    "Hi,\n\nAppreciate the quick turnaround. Let's touch base tomorrow to finalize.\n\nThanks",
    "Hey,\n\nGood progress today. I've noted the changes and will update accordingly.\n\nBest",
    "Hi,\n\nJust confirming I received everything. All clear on my side. Have a great day.\n\nCheers",
    "Hello,\n\nThanks for the reminder. I'll get that sorted by end of day.\n\nRegards",
    "Hi,\n\nLooks great to me. No changes needed. Ready to move forward whenever.\n\nBest",
    "Hey,\n\nHope you're doing well. Wanted to check in and see how things are going.\n\nCheers",
    "Hi,\n\nThanks for your patience. I've wrapped up my part — over to you now.\n\nBest",
]

WARMUP_REPLIES = [
    "Thanks, sounds good!", "Perfect, appreciate it.", "Got it, will do.",
    "Great, thanks for confirming.", "Noted, talk soon.", "Awesome, thank you!",
    "Understood, thanks.", "That works for me.", "Cheers, speak soon.",
]


def _domain_of(email_addr):
    return email_addr.split("@")[-1].lower()


def _build_pool(db):
    """Get ALL warmup-enabled senders across ALL users/modes with app passwords.
    Returns list of (email, decrypted_pw, name, sender_obj)."""
    senders = db.query(Sender).filter(Sender.warmup == True).all()
    pool = []
    for s in senders:
        if s.app_password:
            try:
                pw = security.decrypt(s.app_password)
                pool.append((s.email, pw, s.name or "", s))
            except Exception:
                pass
    return pool


def _pick_targets(from_email, pool, count):
    """Pick warmup targets — NEVER same domain as sender."""
    from_domain = _domain_of(from_email)
    candidates = [p for p in pool if _domain_of(p[0]) != from_domain]
    random.shuffle(candidates)
    return candidates[:count]


def _send_warmup(from_email, from_pw, from_name, to_email):
    subject = random.choice(WARMUP_SUBJECTS)
    body = random.choice(WARMUP_BODIES)
    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["X-Warmup"] = "true"
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.ehlo(); s.starttls(); s.login(from_email, from_pw)
            s.send_message(msg)
        return subject
    except Exception as e:
        print(f"[Warmup] Send fail {from_email}→{to_email}: {e}")
        return None


def _rescue_and_reply(email_addr, app_password):
    """Rescue WU emails from spam, mark important, read, reply."""
    rescued = 0; replied = 0
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, app_password)

        # SPAM → INBOX
        try:
            mail.select('"[Gmail]/Spam"')
            _, data = mail.search(None, 'SUBJECT "WU"')
            for num in data[0].split()[:10]:
                mail.store(num, '+X-GM-LABELS', '\\Inbox')
                mail.store(num, '-X-GM-LABELS', '\\Spam')
                rescued += 1
        except Exception:
            pass

        # INBOX: read + important + reply
        try:
            mail.select("INBOX")
            _, data = mail.search(None, 'UNSEEN SUBJECT "WU"')
            for num in data[0].split()[:8]:
                mail.store(num, '+FLAGS', '\\Seen')
                mail.store(num, '+X-GM-LABELS', '\\Important')
                mail.store(num, '+FLAGS', '\\Flagged')
                _, msgdata = mail.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(msgdata[0][1])
                reply_to = email.utils.parseaddr(msg["From"])[1]
                orig = msg["Subject"] or "WU"
                if reply_to and random.random() > 0.4:
                    r = MIMEText(random.choice(WARMUP_REPLIES), "plain")
                    r["From"] = email_addr; r["To"] = reply_to
                    r["Subject"] = "Re: " + orig; r["X-Warmup"] = "true"
                    try:
                        with smtplib.SMTP("smtp.gmail.com", 587) as s:
                            s.ehlo(); s.starttls(); s.login(email_addr, app_password)
                            s.send_message(r)
                        replied += 1
                    except Exception:
                        pass
        except Exception:
            pass

        mail.logout()
    except Exception as e:
        print(f"[Warmup] IMAP fail {email_addr}: {e}")
    return rescued, replied


def run_warmup_cycle(mode=None):
    """One warmup cycle using the FULL cross-user pool.
    mode is ignored for pairing (pool is global) but used for stats."""
    db = SessionLocal()
    stats = {"sent": 0, "rescued": 0, "replied": 0, "pool_size": 0, "domains": 0}
    try:
        pool = _build_pool(db)
        stats["pool_size"] = len(pool)
        domains = set(_domain_of(p[0]) for p in pool)
        stats["domains"] = len(domains)

        if len(pool) < 2:
            return {"error": "Need at least 2 warmup senders", **stats}
        if len(domains) < 2:
            return {"error": "All senders are same domain. Warmup needs 2+ different domains for safety. Add senders from another domain, or more users need to join the pool.", **stats}

        # Each sender emails cross-domain targets
        for from_email, from_pw, from_name, s_obj in pool:
            targets = _pick_targets(from_email, pool, random.randint(2, 4))
            for to_email, _, _, _ in targets:
                subj = _send_warmup(from_email, from_pw, from_name, to_email)
                if subj:
                    stats["sent"] += 1
                    s_obj.warmup_sent_today = (s_obj.warmup_sent_today or 0) + 1
                time.sleep(random.uniform(3, 8))
        db.commit()

        # Rescue + reply phase
        time.sleep(15)
        for email_addr, pw, _, _ in pool:
            r, rep = _rescue_and_reply(email_addr, pw)
            stats["rescued"] += r
            stats["replied"] += rep

    except Exception as e:
        print(f"[Warmup] Cycle error: {e}")
        stats["error"] = str(e)
    finally:
        db.close()
    return stats


def _warmup_loop(interval_minutes):
    global _warmup_running
    while _warmup_running:
        print("[Warmup] Running cross-user cycle...")
        stats = run_warmup_cycle()
        print(f"[Warmup] Done: {stats}")
        for _ in range(int(interval_minutes * 60)):
            if not _warmup_running:
                break
            time.sleep(1)


def start_warmup(mode="client", interval_minutes=90):
    global _warmup_thread, _warmup_running
    if _warmup_running:
        return {"status": "already running"}
    _warmup_running = True
    _warmup_thread = threading.Thread(target=_warmup_loop, args=(interval_minutes,), daemon=True)
    _warmup_thread.start()
    return {"status": "started", "interval_minutes": interval_minutes}


def stop_warmup():
    global _warmup_running
    _warmup_running = False
    return {"status": "stopped"}


def warmup_status():
    return {"running": _warmup_running}


def pool_info(db):
    """Info about the warmup pool."""
    pool = _build_pool(db)
    domains = {}
    for em, _, _, _ in pool:
        d = _domain_of(em)
        domains[d] = domains.get(d, 0) + 1
    return {
        "pool_size": len(pool),
        "domains": len(domains),
        "domain_breakdown": domains,
        "can_warmup": len(domains) >= 2,
    }
