"""Real, multi-signal sender health scoring.

The old score just did +1 per warmup send, so a sender whose mail all bounced
still looked healthy. This computes a 0-100 score from signals we actually have:

    warmup progress    how far into the gradual ramp the sender is
    bounce rate        failed / total_sent  (biggest negative signal)
    reply activity     replies seen (positive — real engagement)
    volume maturity    how much history exists (a brand-new inbox is unproven)
    auth bonus         SPF/DKIM/DMARC pass (from the deliverability checker)

Every number is derived from the sender's own real activity — nothing is
fabricated. Returns the score plus a breakdown so the UI can explain it and the
AI assistant can give grounded advice.
"""
from __future__ import annotations
from datetime import datetime, date


def _bounce_rate(sender) -> float:
    total = (sender.total_sent or 0)
    if total <= 0:
        return 0.0
    return min(1.0, (sender.failed or 0) / total)


def _reply_rate(sender) -> float:
    total = (sender.total_sent or 0)
    if total <= 0:
        return 0.0
    return min(1.0, (sender.replies or 0) / total)


def per_mode_stats(db, sender_email: str, mode: str) -> dict:
    """How much THIS sender has done in ONE mode (client/blog/vendor), counted
    from OutreachEntry rows — the real per-mode sending record. The Sender row
    keeps one combined counter; this splits it out so the client dashboard shows
    only client activity and the blog dashboard shows only blog activity, even
    when the same Gmail address is used in both."""
    from .crm_models import OutreachEntry
    q = db.query(OutreachEntry).filter(
        OutreachEntry.sender_email == sender_email,
        OutreachEntry.mode == mode)
    sent = q.filter(OutreachEntry.status.in_(
        ["sent", "opened", "replied", "bounced", "unsubscribed"])).count()
    replies = q.filter(OutreachEntry.status == "replied").count()
    bounced = q.filter(OutreachEntry.status == "bounced").count()
    return {"sent": sent, "replies": replies, "bounced": bounced}


def compute_health(sender, auth_score: int | None = None) -> dict:
    """Return {score, level, risk, breakdown[]} for one sender.

    auth_score (0-100 from deliverability.check_domain) is optional; when given
    it nudges the score up or down, because good SPF/DKIM/DMARC materially helps
    deliverability and missing auth materially hurts it.
    """
    breakdown = []

    # --- Warmup progress: 0..30 pts. A mature warmup (~30 days) is fully ramped.
    wday = max(0, sender.warmup_day or 0)
    warm_pts = min(30, round(wday / 30 * 30))
    breakdown.append(("Warmup progress", warm_pts, 30,
                      f"day {wday} of the ramp"))

    # --- Volume maturity: 0..20 pts. History proves the inbox can send.
    total = sender.total_sent or 0
    vol_pts = min(20, round((total / 200) * 20))   # ~200 sends = full marks
    breakdown.append(("Sending history", vol_pts, 20,
                      f"{total} total sent"))

    # --- Bounce health: 0..30 pts. Low bounce = healthy; high bounce = danger.
    br = _bounce_rate(sender)
    bounce_pts = round(max(0.0, 1 - br / 0.10) * 30)   # 0% bounce=30pts, 10%+=0
    bounce_pts = max(0, min(30, bounce_pts))
    breakdown.append(("Bounce health", bounce_pts, 30,
                      f"{br*100:.1f}% bounce rate"))

    # --- Engagement: 0..20 pts. Replies are the strongest positive signal.
    rr = _reply_rate(sender)
    eng_pts = min(20, round(rr / 0.05 * 20))   # 5%+ reply rate = full marks
    breakdown.append(("Engagement", eng_pts, 20,
                      f"{rr*100:.1f}% reply rate"))

    base = warm_pts + vol_pts + bounce_pts + eng_pts   # 0..100

    # --- Auth adjustment: +/- up to ~10, from real SPF/DKIM/DMARC.
    auth_adj = 0
    if auth_score is not None:
        # 100 -> +8, 50 -> -2, 0 -> -12 (scaled). Rewards good auth, punishes bad.
        auth_adj = round((auth_score - 70) / 10)
        auth_adj = max(-12, min(8, auth_adj))
        breakdown.append(("Authentication", auth_adj, 8,
                          f"domain auth score {auth_score}/100"))

    score = max(0, min(100, base + auth_adj))

    # Level + risk band
    is_new = (sender.total_sent or 0) < 30 and (sender.warmup_day or 0) < 10
    if is_new:
        # A brand-new inbox hasn't earned a high score yet, but it isn't
        # "unhealthy" — it's just early. Label it honestly as still warming.
        level, risk = "warming up", "low"
    elif score >= 85:
        level, risk = "excellent", "low"
    elif score >= 70:
        level, risk = "good", "low"
    elif score >= 50:
        level, risk = "fair", "medium"
    else:
        level, risk = "poor", "high"

    # Recompute a couple of live risk flags for the UI / assistant.
    risks = []
    if br >= 0.05:
        risks.append(f"Bounce rate {br*100:.1f}% is high — pause outreach and warm up more.")
    if total >= 20 and rr < 0.01:
        risks.append("Almost no replies — engagement is low; check content and targeting.")
    if auth_score is not None and auth_score < 60:
        risks.append("Domain authentication needs attention (SPF/DKIM/DMARC).")
    if wday < 14 and total > 100:
        risks.append("Sending volume is high for how new this inbox is — ramp more slowly.")

    return {
        "score": score, "level": level, "risk": risk,
        "breakdown": [{"label": l, "points": p, "max": m, "detail": d}
                      for (l, p, m, d) in breakdown],
        "risks": risks,
        "bounce_rate": round(br * 100, 1),
        "reply_rate": round(rr * 100, 1),
    }


def recommend(sender, health: dict) -> str:
    """One grounded, human recommendation from the health picture."""
    s = health["score"]
    if health.get("level") == "warming up":
        return "New inbox — keep warmup running and don't send outreach yet."
    if health.get("risks"):
        # Lead with the most pressing risk.
        return health["risks"][0]
    if s >= 85:
        return "Health is excellent — safe to continue current outreach volume."
    if s >= 70:
        return "Health is good. You can gradually increase outreach volume."
    if s >= 50:
        return "Health is fair — keep warmup running and raise volume slowly."
    return "Health is low — pause outreach, keep warmup on, and let reputation recover."


def record_snapshot(db, sender, health: dict, auth_score=None):
    """Save today's health numbers for a sender (one row per day; updates if it
    already ran today). This builds the history that trend charts read from."""
    from .crm_models import HealthSnapshot
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    row = db.query(HealthSnapshot).filter(
        HealthSnapshot.sender_email == sender.email,
        HealthSnapshot.day == today).first()
    if row is None:
        row = HealthSnapshot(sender_email=sender.email, day=today)
        db.add(row)
    row.health = health.get("score", 0)
    row.bounce_rate = health.get("bounce_rate", 0)
    row.reply_rate = health.get("reply_rate", 0)
    row.auth_score = auth_score or 0
    row.total_sent = sender.total_sent or 0
    row.warmup_sent = sender.warmup_sent_today or 0
    db.commit()


def get_history(db, sender_email: str, days: int = 30):
    """Recorded daily snapshots for one sender, oldest-first, for charts."""
    from .crm_models import HealthSnapshot
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = (db.query(HealthSnapshot)
            .filter(HealthSnapshot.sender_email == sender_email,
                    HealthSnapshot.day >= cutoff)
            .order_by(HealthSnapshot.day.asc()).all())
    return [{"day": r.day, "health": r.health, "bounce_rate": r.bounce_rate,
             "reply_rate": r.reply_rate, "auth_score": r.auth_score,
             "total_sent": r.total_sent, "warmup_sent": r.warmup_sent}
            for r in rows]
