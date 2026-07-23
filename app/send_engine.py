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
import uuid
from datetime import datetime, timedelta
from .database import SessionLocal, Sender
from .crm_models import OutreachEntry, EventLog, Campaign
from .gmail_send import send_via_smtp, send_via_oauth
from .email_templates import get_template, render_template
from .blog_templates import get_blog_template, render_blog_template
from . import security
from .config import settings

_send_threads = {}
_stop_flags = {}
# Which campaign is currently sending for each mode. Prevents two campaigns in
# the same mode from grabbing the same pending emails (which caused duplicates).
_sending_modes = {}


def _get_senders(db, mode):
    """Get all active senders for this mode, ordered by ID.
    Excludes senders that failed auth or are still verifying.
    Blog mode reuses CLIENT senders (blog research pitches clients)."""
    sender_mode = "client" if mode == "blog" else mode
    rows = db.query(Sender).filter(
        Sender.mode == sender_mode,
        Sender.status.notin_(["auth_failed", "verifying"])
    ).order_by(Sender.id).all()
    # Fallback: if blog/client has no senders, use any active sender
    if not rows and mode == "blog":
        rows = db.query(Sender).filter(
            Sender.status.notin_(["auth_failed", "verifying"])
        ).order_by(Sender.id).all()
    return rows


def _build_variables(entry, sender, unsub_token=""):
    """Build template variables. Body uses clean name (Today), subject uses full domain (Today.com).
    unsub_token = unique token for this email's unsubscribe link."""
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

    # Unsubscribe URL: token-based (works with /unsubscribe?t=TOKEN endpoint)
    # Unsubscribe URL: token-based, using the configured public base URL.
    # (127.0.0.1 for local testing; a public domain/ngrok URL for real sends.)
    base = settings.PUBLIC_URL
    unsub_url = f"{base}/unsubscribe?t={unsub_token}" if unsub_token else f"{base}/unsubscribe?t=none"

    # Blog research: the site + article where we spotted their link. These make
    # the pitch specific ("I saw your link on X in this piece") instead of generic.
    ref_site = (getattr(entry, "ref_site", "") or "").replace("www.", "")
    ref_article = getattr(entry, "ref_article", "") or ""
    ref_site_name = ref_site.split(".")[0].replace("-", " ").title() if ref_site else ""

    return {
        # company_name in body = clean name only ("Today")
        "company_name": company,
        "ref_site": ref_site,                 # techbullion.com
        "ref_site_name": ref_site_name,       # TechBullion
        "ref_article": ref_article,           # full URL of the article
        # website/site in subject = full domain ("Today.com")
        "website": site_full,
        "sender_name": (sender.name or sender.email.split("@")[0]).split()[0].title(),
        "your_company": "Uplyncio",
        "your_website": "uplyncio.com",
        "unsubscribe_url": unsub_url,
    }


def start_campaign_send(campaign_id: int, mode: str, emails_per_batch: int = 10,
                        delay_seconds: int = 30, scheduled_time: str = None,
                        sender_filter: str = None, total_target: int = 0,
                        autopilot: bool = False, min_delay: int = 0, max_delay: int = 0):
    """delay_seconds is the base gap. If min_delay/max_delay given, each email
    waits a RANDOM time in that range (more natural, no fixed pattern)."""
    import random
    # If explicit range not given, build a natural range around delay_seconds:
    # e.g. delay_seconds=30 -> random 15-40ish. Range is [delay*0.5, delay*1.35].
    if min_delay <= 0:
        min_delay = max(10, int(delay_seconds * 0.5))
    if max_delay <= 0:
        max_delay = int(delay_seconds * 1.35)
    if max_delay < min_delay:
        max_delay = min_delay + 10
    """Start sending. sender_filter = comma-separated emails (only use these senders)."""
    # Resume-safe: only refuse if a thread is ACTUALLY still alive. A stale entry
    # from a stopped/finished campaign is cleaned up so resume works.
    existing = _send_threads.get(campaign_id)
    if existing is not None:
        if existing.is_alive():
            return {"error": "Campaign already sending"}
        # Dead/finished thread left an entry — clear it so we can resume
        _send_threads.pop(campaign_id, None)
    _stop_flags.pop(campaign_id, None)  # clear any old stop flag before resuming

    # CRITICAL: only ONE campaign per mode may send at a time. Pending emails are
    # selected by MODE, so two campaigns running together would both grab the same
    # emails and send every message twice.
    other = _sending_modes.get(mode)
    if other and other != campaign_id:
        t_other = _send_threads.get(other)
        if t_other is not None and t_other.is_alive():
            return {"error": f"Campaign #{other} is already sending for '{mode}'. "
                             f"Stop it first."}
    _sending_modes[mode] = campaign_id

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
            # STRICT: if the user picked specific senders, use ONLY those.
            if sender_filter:
                allowed = [e.strip().lower() for e in sender_filter.split(",") if e.strip()]
                usable = [s for s in senders if s.email.lower() in allowed]
                missing = [a for a in allowed
                           if a not in [s.email.lower() for s in usable]]
                if missing:
                    print(f"[SendEngine] These chosen senders can't be used "
                          f"(not found / auth failed): {', '.join(missing)}")
                senders = usable
            if not senders:
                campaign.status = "error: no senders"
                db.commit()
                print("[SendEngine] Campaign stopped — none of the chosen senders are usable.")
                return
            print(f"[SendEngine] Campaign #{campaign_id}: sending "
                  f"{total_target if total_target > 0 else 'all pending'} email(s) "
                  f"via {len(senders)} sender(s): "
                  f"{', '.join(s.email for s in senders)}")

            # Get pending entries.
            # When a target is set we deliberately fetch MORE than the target:
            # some rows turn out to be unsendable (bad address, unsubscribed,
            # already claimed) and must be replaced, otherwise asking for 100
            # would deliver fewer than 100. The loop stops the moment exactly
            # `total_target` emails have actually gone out.
            q = db.query(OutreachEntry).filter(
                OutreachEntry.mode == mode,
                OutreachEntry.status.in_(["pending", "queued"])
            ).order_by(OutreachEntry.id)
            if total_target > 0:
                pending = q.limit(total_target * 4 + 200).all()
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
            # Track when each sender last sent, so the gap applies PER SENDER.
            # Round-robin: sender1, sender2, sender3, sender4, then sender1 again —
            # and sender1's 2nd email waits delay_seconds after sender1's 1st (not
            # after sender4's). Different senders send back-to-back with no wait.
            last_sent_at = {}

            for i, entry in enumerate(pending):
                # EXACT TARGET: stop the moment we've sent what was asked for.
                if total_target > 0 and sent_count >= total_target:
                    print(f"[SendEngine] Target reached — sent exactly "
                          f"{sent_count}/{total_target}.")
                    break

                # Check if manually stopped (fast in-memory flag, not DB)
                if stop_flag["stop"]:
                    print(f"[SendEngine] Campaign #{campaign_id} manually stopped.")
                    break

                # ATOMIC CLAIM — the single most important duplicate guard.
                # Flip this row pending/queued -> "sending" in ONE SQL statement.
                # If it updates 0 rows, someone else already took it, so skip.
                # This makes double-sends impossible even if two loops overlap.
                try:
                    claimed = db.query(OutreachEntry).filter(
                        OutreachEntry.id == entry.id,
                        OutreachEntry.status.in_(["pending", "queued"])
                    ).update({"status": "sending"}, synchronize_session=False)
                    db.commit()
                except Exception:
                    db.rollback()
                    claimed = 0
                if not claimed:
                    continue  # already claimed/sent by someone else — skip it

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

                # PER-SENDER gap: if THIS sender sent recently, wait out the remainder
                # of its personal gap. Gap is RANDOM in [min_delay, max_delay] each time
                # so there's no fixed pattern (looks natural to Gmail). Other senders
                # are unaffected and send in parallel.
                prev = last_sent_at.get(sender.email)
                if prev is not None:
                    this_gap = random.randint(min_delay, max_delay)
                    elapsed = time.time() - prev
                    remaining = this_gap - elapsed
                    if remaining > 0:
                        print(f"[SendEngine] {sender.email} waiting {remaining:.0f}s (random {this_gap}s gap)...")
                        waited = 0
                        while waited < remaining and not stop_flag["stop"]:
                            time.sleep(min(1, remaining - waited))
                            waited += 1
                        if stop_flag["stop"]:
                            break

                # Generate unique unsubscribe token for this email
                token = uuid.uuid4().hex
                entry.unsub_token = token

                # Round-robin template (each mode has its own set)
                if mode == "vendor":
                    from .vendor_templates import get_vendor_template, render_vendor_template
                    template = get_vendor_template(template_idx)
                    variables = _build_variables(entry, sender, unsub_token=token)
                    rendered = render_vendor_template(template, variables)
                elif mode == "blog" and (entry.ref_article or ""):
                    # Blog research prospects get templates that name the exact
                    # site and article where we found their link.
                    template = get_blog_template(template_idx)
                    variables = _build_variables(entry, sender, unsub_token=token)
                    rendered = render_blog_template(template, variables)
                else:
                    # No article on record (older prospect) — use the generic
                    # pitch rather than sending a mail with blanks in it.
                    template = get_template(template_idx)
                    variables = _build_variables(entry, sender, unsub_token=token)
                    rendered = render_template(template, variables)
                template_idx += 1

                # OPEN TRACKING: inject an invisible 1x1 pixel at the end of the
                # email body. When the recipient opens the email, their client
                # loads this image, which hits /track/open?t=TOKEN and marks the
                # email as "opened". Uses the same token as unsubscribe.
                tracking_pixel = (
                    f'<img src="{settings.PUBLIC_URL}/track/open?t={token}" '
                    f'width="1" height="1" alt="" '
                    f'style="display:none;width:1px;height:1px" />'
                )
                rendered["body_html"] = rendered["body_html"] + tracking_pixel

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

                # Send email — supports BOTH OAuth and app-password senders.
                try:
                    sent_ok = False
                    if sender.method == "app_password":
                        app_pw = security.decrypt(sender.app_password) if sender.app_password else ""
                        if app_pw:
                            res = send_via_smtp(
                                sender_email=sender.email,
                                sender_name=sender.name or "",
                                app_password=app_pw,
                                to=entry.email,
                                subject=rendered["subject"],
                                body_html=rendered["body_html"],
                            )
                            entry.message_id = res.get("message_id", "")
                            sent_ok = True
                    elif sender.method == "oauth":
                        import json
                        creds_json = security.decrypt(sender.oauth_token) if sender.oauth_token else ""
                        if creds_json:
                            creds_dict = json.loads(creds_json)
                            result = send_via_oauth(
                                creds_dict=creds_dict,
                                sender_email=sender.email,
                                sender_name=sender.name or "",
                                to=entry.email,
                                subject=rendered["subject"],
                                body_html=rendered["body_html"],
                            )
                            # OAuth may refresh the token — save the updated one
                            if result.get("creds"):
                                sender.oauth_token = security.encrypt(json.dumps(result["creds"]))
                            entry.message_id = result.get("message_id", "")
                            entry.gmail_id = result.get("gmail_id", "")
                            sent_ok = True

                    if sent_ok:
                        # Tell the label worker what this message should be tagged as
                        entry.label_target = f"{entry.mode}:0"
                        entry.status = "sent"
                        entry.sent_at = datetime.utcnow()
                        entry.sender_email = sender.email
                        entry.subject = rendered["subject"]
                        sender.sent_today = (sender.sent_today or 0) + 1
                        sender.total_sent = (sender.total_sent or 0) + 1
                        db.add(EventLog(campaign_id=campaign_id, sender_id=sender.id,
                                       type="sent", contact_id=0))
                        db.commit()
                        sent_count += 1
                        last_sent_at[sender.email] = time.time()
                        try:
                            from . import gmail_labels
                            gmail_labels.kick()   # label it almost immediately
                        except Exception:
                            pass
                        print(f"[SendEngine] Sent #{sent_count}: {entry.email} via {sender.email}")
                    else:
                        entry.status = "failed"
                        db.commit()
                        print(f"[SendEngine] FAILED (no valid creds): {entry.email} via {sender.email}")

                except Exception as e:
                    entry.status = "bounced"
                    db.add(EventLog(campaign_id=campaign_id, sender_id=sender.id,
                                   type="failed", contact_id=0))
                    db.commit()
                    print(f"[SendEngine] Failed: {entry.email} — {e}")

                # (Gap is handled per-sender at the top of the loop — no global wait here,
                # so different senders send back-to-back while each sender paces itself.)

            # Campaign complete
            if total_target > 0 and sent_count < total_target:
                # Ran out of sendable contacts before hitting the target — say so
                # plainly instead of silently reporting "completed".
                left = db.query(OutreachEntry).filter(
                    OutreachEntry.mode == mode,
                    OutreachEntry.status.in_(["pending", "queued"])).count()
                campaign.status = "completed"
                db.commit()
                print(f"[SendEngine] Campaign #{campaign_id} finished with "
                      f"{sent_count}/{total_target} sent — ran out of valid "
                      f"contacts ({left} left in the list, but they were "
                      f"unsendable: bad address, unsubscribed or already sent).")
            else:
                campaign.status = "completed"
                db.commit()
                print(f"[SendEngine] Campaign #{campaign_id} done. "
                      f"Sent {sent_count} email(s)"
                      + (f" — exactly the {total_target} requested."
                         if total_target > 0 else "."))

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
            # Release this mode so another campaign may send later
            if _sending_modes.get(mode) == campaign_id:
                _sending_modes.pop(mode, None)

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
