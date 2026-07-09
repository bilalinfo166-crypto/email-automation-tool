"""Compliance layer. Company profile fills the footer once; campaigns add the
per-message reason. A campaign cannot send unless the profile is complete, the
campaign fields are filled, and lawful basis is confirmed."""
import re
import secrets
import functools
from sqlalchemy.orm import Session
from .crm_models import Suppression, Campaign, CompanyProfile

try:
    import dns.resolver
    HAS_DNS = True
except Exception:
    HAS_DNS = False

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Campaign-level required fields (identity/address come from the company profile).
REQUIRED_CAMPAIGN_FIELDS = [
    ("subject", "Subject line"),
    ("reason_for_contact", "Reason the recipient is being contacted"),
    ("body_html", "Email body"),
]
# One-time company profile fields.
REQUIRED_PROFILE_FIELDS = [
    ("company_name", "Company name"),
    ("website_url", "Website URL"),
    ("business_address", "Business address"),
    ("sender_name", "Sender name"),
    ("reply_to_email", "Reply-to email"),
]

# Phrases in a reply that mean "stop emailing me".
UNSUB_PHRASES = ["unsubscribe", "remove me", "take me off", "opt out", "opt-out", "stop emailing"]
NOT_INTERESTED_PHRASES = ["not interested", "no thanks", "no thank you", "stop", "leave me alone",
                          "do not contact", "don't contact", "please remove", "unsolicited"]


def valid_email(e: str) -> bool:
    return bool(EMAIL_RE.match((e or "").strip().lower()))


@functools.lru_cache(maxsize=20000)
def domain_has_mx(domain: str) -> bool:
    if not HAS_DNS:
        return True
    try:
        if dns.resolver.resolve(domain, "MX", lifetime=8):
            return True
    except Exception:
        try:
            dns.resolver.resolve(domain, "A", lifetime=6)
            return True
        except Exception:
            return False
    return False


# ---------- company profile ----------

def get_profile(db: Session) -> CompanyProfile | None:
    return db.get(CompanyProfile, 1)


def profile_missing(p: CompanyProfile | None) -> list[str]:
    if not p:
        return [label for _, label in REQUIRED_PROFILE_FIELDS]
    return [label for attr, label in REQUIRED_PROFILE_FIELDS if not (getattr(p, attr) or "").strip()]


# ---------- suppression ----------

def is_suppressed(db: Session, email: str) -> bool:
    return db.query(Suppression).filter(Suppression.email == email.lower()).first() is not None


def add_suppression(db: Session, email: str, reason: str = "unsubscribe"):
    email = email.strip().lower()
    if not is_suppressed(db, email):
        db.add(Suppression(email=email, reason=reason))
        db.commit()


# ---------- reply classification ----------

def classify_optout(text: str):
    """Return 'unsubscribe', 'not_interested', or None based on reply wording."""
    t = (text or "").lower()
    if any(p in t for p in UNSUB_PHRASES):
        return "unsubscribe"
    if any(p in t for p in NOT_INTERESTED_PHRASES):
        return "not_interested"
    return None


# ---------- campaign readiness (hard gate) ----------

def missing_fields(c: Campaign) -> list[str]:
    return [label for attr, label in REQUIRED_CAMPAIGN_FIELDS if not (getattr(c, attr) or "").strip()]


def assert_sendable(db: Session, c: Campaign):
    """Raises ValueError unless profile complete + campaign fields set + lawful basis + approved."""
    pmiss = profile_missing(get_profile(db))
    if pmiss:
        raise ValueError("Complete your company profile first (missing: " + ", ".join(pmiss) + ").")
    miss = missing_fields(c)
    if miss:
        raise ValueError("Campaign is missing required fields: " + ", ".join(miss))
    if not c.lawful_basis_confirmed:
        raise ValueError("Lawful basis / permission to contact has not been confirmed.")
    if c.status not in ("approved", "sending"):
        raise ValueError(f"Campaign must be approved before sending (current: {c.status}).")


# ---------- required footer (from the company profile) ----------

def new_unsub_token() -> str:
    return secrets.token_urlsafe(16)


def build_footer(p: CompanyProfile, c: Campaign, unsubscribe_link: str) -> str:
    return f"""
    <hr style="border:none;border-top:1px solid #e4e9ef;margin:28px 0 14px">
    <div style="font-family:Arial,sans-serif;font-size:12px;color:#6b7684;line-height:1.6">
      <p style="margin:0 0 8px">You are receiving this email because {c.reason_for_contact}</p>
      <p style="margin:0 0 8px">{p.sender_name} &middot; {p.company_name}<br>{p.business_address}<br>
        <a href="{p.website_url}" style="color:#6b7684">{p.website_url}</a></p>
      <p style="margin:0">
        <a href="{unsubscribe_link}" style="color:#0b3d5c;font-weight:bold">Unsubscribe</a>
        &mdash; you will not be emailed again.
      </p>
    </div>
    """


def compose_email(db: Session, c: Campaign, unsubscribe_link: str) -> str:
    p = get_profile(db)
    return (c.body_html or "") + build_footer(p, c, unsubscribe_link)
