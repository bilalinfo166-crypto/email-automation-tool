"""Autopilot — chains the existing scraper -> campaign -> send -> follow-up
pieces into one hands-free loop, per mode (vendor/client/blog), with safety
limits so it can't wreck sender reputation.

It builds NOTHING new for scraping/sending — it drives the parts that already
work, in order, on a schedule. State + settings live in app_settings (JSON) so
they survive restarts.

Safety limits (always on):
  - only VERIFIED senders (never auth_failed / verifying)
  - a daily send ceiling per mode (user-set, capped)
  - warmup-safe: skips senders whose warmup day is very low unless allowed
  - respects the existing per-sender / daily follow-up caps
"""
from __future__ import annotations
import json, time, threading
from datetime import datetime

# ---- settings persistence (reuses the app_settings key/value table) ----

def _key(mode): return f"autopilot_{mode}"

DEFAULTS = {
    "enabled": False,
    "domains": [],           # seed domains/sites to scrape
    "keywords": "",          # optional search keywords (if scraper supports)
    "sender_emails": [],     # which senders to send from ([] = all verified)
    "daily_limit": 50,       # max emails/day this mode (hard-capped below)
    "send_start_hour": 9,    # local hour window
    "send_end_hour": 18,
    "template_id": None,     # which template to use ([] = default)
    "min_warmup_day": 3,     # don't autosend from very new inboxes
    "last_run": None,
    "last_stage": "idle",    # idle/scraping/building/sending/done
    "status_note": "",
}

HARD_DAILY_CAP = 200         # absolute ceiling regardless of user setting


def get_settings(db, mode: str) -> dict:
    from .crm_models import AppSetting
    row = db.query(AppSetting).filter(AppSetting.key == _key(mode)).first()
    s = dict(DEFAULTS)
    if row and row.value:
        try:
            s.update(json.loads(row.value))
        except Exception:
            pass
    return s


def save_settings(db, mode: str, patch: dict) -> dict:
    from .crm_models import AppSetting
    cur = get_settings(db, mode)
    cur.update(patch or {})
    # clamp the daily limit to the hard cap no matter what the user sends
    try:
        cur["daily_limit"] = max(1, min(HARD_DAILY_CAP, int(cur.get("daily_limit", 50))))
    except Exception:
        cur["daily_limit"] = 50
    row = db.query(AppSetting).filter(AppSetting.key == _key(mode)).first()
    if row is None:
        row = AppSetting(key=_key(mode), value=json.dumps(cur))
        db.add(row)
    else:
        row.value = json.dumps(cur)
        row.updated_at = datetime.utcnow()
    db.commit()
    return cur


def _set_stage(db, mode, stage, note=""):
    save_settings(db, mode, {"last_stage": stage, "status_note": note,
                             "last_run": datetime.utcnow().isoformat()})


# ---- safety helpers ----

def _verified_senders(db, mode, settings):
    from .database import Sender
    q = db.query(Sender).filter(
        Sender.mode == mode,
        Sender.status.notin_(["auth_failed", "verifying"]))
    senders = q.all()
    want = set(settings.get("sender_emails") or [])
    if want:
        senders = [s for s in senders if s.email in want]
    # warmup-safe: skip very new inboxes
    minday = settings.get("min_warmup_day", 3)
    senders = [s for s in senders if (s.warmup_day or 0) >= minday or not s.warmup]
    return senders


def _sent_today(db, mode):
    """How many real outreach emails already went out today for this mode."""
    from .crm_models import OutreachEntry
    from datetime import datetime, time as _t
    start = datetime.combine(datetime.utcnow().date(), _t.min)
    return db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode,
        OutreachEntry.status.in_(["sent", "opened", "replied", "bounced"]),
        OutreachEntry.sent_at >= start).count()


def _within_hours(settings):
    h = datetime.now().hour
    return settings.get("send_start_hour", 9) <= h < settings.get("send_end_hour", 18)


# ---- the one-cycle driver (called by the loop) ----

def run_cycle(db, mode: str) -> dict:
    """Advance Autopilot by one cycle for a mode. Safe to call repeatedly."""
    s = get_settings(db, mode)
    if not s.get("enabled"):
        return {"mode": mode, "skipped": "disabled"}

    # Safety gate 1: verified senders exist
    senders = _verified_senders(db, mode, s)
    if not senders:
        _set_stage(db, mode, "idle", "No verified senders available.")
        return {"mode": mode, "skipped": "no verified senders"}

    # Safety gate 2: daily ceiling
    sent = _sent_today(db, mode)
    if sent >= s["daily_limit"]:
        _set_stage(db, mode, "done", f"Daily limit reached ({sent}/{s['daily_limit']}).")
        return {"mode": mode, "skipped": "daily limit reached", "sent_today": sent}

    # Safety gate 3: sending window
    if not _within_hours(s):
        _set_stage(db, mode, "idle", "Outside sending hours.")
        return {"mode": mode, "skipped": "outside hours"}

    remaining = s["daily_limit"] - sent

    # Stage machine: make sure there's pending data; if not, scrape. Then build
    # campaigns and send a bounded batch.
    from .crm_models import OutreachEntry
    pending = db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode, OutreachEntry.status == "pending").count()

    result = {"mode": mode, "sent_today": sent, "remaining": remaining}

    if pending == 0:
        # kick off a scrape from the configured domains (non-blocking job)
        domains = s.get("domains") or []
        if not domains:
            _set_stage(db, mode, "idle", "No domains configured to scrape.")
            result["note"] = "no domains"
            return result
        try:
            from . import scraper_jobs
            job = scraper_jobs.create_job(
                db, mode=mode, name=f"Autopilot {mode} scrape",
                domains=domains, source="autopilot")
            _set_stage(db, mode, "scraping", f"Scraping {len(domains)} domain(s).")
            result["scrape_job"] = getattr(job, "id", None)
        except Exception as e:
            _set_stage(db, mode, "idle", f"Scrape failed: {e}")
            result["error"] = str(e)
        return result

    # We have pending emails -> build campaigns and send a bounded batch,
    # capped by how many we're still allowed to send today.
    _set_stage(db, mode, "building", f"{pending} prospect(s) ready.")
    from .crm_models import Campaign, QueueItem
    batch_cap = min(remaining, 20)   # small, warmup-safe batches per cycle
    picked = db.query(OutreachEntry).filter(
        OutreachEntry.mode == mode, OutreachEntry.status == "pending"
    ).order_by(OutreachEntry.id).limit(batch_cap).all()
    if not picked:
        _set_stage(db, mode, "idle", "Nothing pending to send.")
        return result

    # round-robin the picked emails across verified senders
    camp = Campaign(mode=mode,
                    name=f"Autopilot {mode} — {datetime.utcnow():%b %d %H:%M}",
                    status="ready")
    db.add(camp); db.commit(); db.refresh(camp)
    si = 0
    for entry in picked:
        sender = senders[si % len(senders)]
        si += 1
        entry.status = "queued"
        entry.sender_email = sender.email
        db.add(QueueItem(campaign_id=camp.id, contact_id=0,
                         sender_id=sender.id, email=entry.email,
                         subject="", body_html=""))
    db.commit()

    # fire the existing send engine (rate-controlled, non-blocking)
    try:
        from . import send_engine
        send_engine.start_campaign_send(
            campaign_id=camp.id, mode=mode,
            emails_per_batch=10, delay_seconds=60)
        _set_stage(db, mode, "sending",
                   f"Sending {len(picked)} email(s) from {len(senders)} sender(s).")
        result["campaign_id"] = camp.id
        result["queued"] = len(picked)
    except Exception as e:
        _set_stage(db, mode, "idle", f"Send failed: {e}")
        result["error"] = str(e)
    return result


# ---- background loop ----

_thread = None
_stop = False

def start():
    global _thread, _stop
    if _thread and _thread.is_alive():
        return
    _stop = False
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()

def stop():
    global _stop
    _stop = True

def _loop():
    from .database import SessionLocal
    while not _stop:
        for _ in range(60 * 15):   # every 15 min
            if _stop:
                return
            time.sleep(1)
        for mode in ("vendor", "client", "blog"):
            db = SessionLocal()
            try:
                run_cycle(db, mode)
            except Exception as e:
                print(f"[Autopilot] {mode} error: {e}")
            finally:
                db.close()
