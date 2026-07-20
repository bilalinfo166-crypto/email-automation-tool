"""Request / response shapes for the API."""
import re
from pydantic import BaseModel, field_validator
from .config import settings

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _check_domain(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    if settings.SENDING_DOMAIN and not email.endswith("@" + settings.SENDING_DOMAIN):
        raise ValueError(f"Email must be on {settings.SENDING_DOMAIN}.")
    return email


class AppPasswordSenderIn(BaseModel):
    email: str
    name: str = ""
    app_password: str
    daily_cap: int = 150
    warmup: bool = True
    mode: str = "vendor"

    @field_validator("email")
    @classmethod
    def val_email(cls, v):
        return _check_domain(v)

    @field_validator("app_password")
    @classmethod
    def val_pass(cls, v):
        code = re.sub(r"\s+", "", v)
        if not re.fullmatch(r"[A-Za-z]{16}", code):
            raise ValueError("App password must be the 16-letter code from Google.")
        return code


class TestEmailIn(BaseModel):
    to: str
    subject: str = "Warmwire test email"
    body_html: str = "<p>Hello! This is a test send from Warmwire ✅</p>"


class SenderOut(BaseModel):
    id: int
    email: str
    name: str
    method: str
    daily_cap: int
    warmup: bool
    status: str
    health: int
    sent_today: int
    total_sent: int
    replies: int
    failed: int
    opened: int

    class Config:
        from_attributes = True
