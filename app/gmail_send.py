"""Two ways to actually send an email: Gmail API (OAuth) or SMTP (app password)."""
import base64
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from googleapiclient.discovery import build

from .gmail_oauth import credentials_from_dict


def _build_message(sender_email: str, sender_name: str, to: str, subject: str,
                   body_html: str, message_id: str = "") -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    from_header = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["From"] = from_header
    msg["To"] = to
    msg["Subject"] = subject
    # A stable Message-ID lets us find this exact message in Sent Mail afterwards
    # (that's how the Gmail label gets attached to it).
    if message_id:
        msg["Message-ID"] = message_id
    msg["X-Mailer"] = "WarmWire/1.0"
    msg["X-WarmWire"] = "sent-via-warmwire"
    msg.attach(MIMEText(body_html, "html"))
    return msg


def new_message_id(sender_email: str) -> str:
    """Build a unique Message-ID we control, so we can locate the sent copy."""
    import uuid as _uuid
    domain = sender_email.split("@")[-1] if "@" in sender_email else "warmwire.local"
    return f"<ww-{_uuid.uuid4().hex}@{domain}>"


def send_via_oauth(creds_dict: dict, sender_email: str, sender_name: str,
                   to: str, subject: str, body_html: str,
                   message_id: str = "") -> dict:
    """Send using the Gmail API with the sender's OAuth credentials."""
    creds = credentials_from_dict(creds_dict)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    message_id = message_id or new_message_id(sender_email)
    msg = _build_message(sender_email, sender_name, to, subject, body_html, message_id)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    # If credentials were refreshed, return the possibly-updated token so caller can save it
    refreshed = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    # gmail_id = Gmail's own id (used to attach labels via the API)
    return {"id": result.get("id"), "gmail_id": result.get("id"),
            "message_id": message_id, "creds": refreshed}


def send_via_smtp(sender_email: str, sender_name: str, app_password: str,
                  to: str, subject: str, body_html: str,
                  message_id: str = "") -> dict:
    """Send using Gmail SMTP with a 16-char app password."""
    message_id = message_id or new_message_id(sender_email)
    msg = _build_message(sender_email, sender_name, to, subject, body_html, message_id)
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
    return {"id": "smtp-ok", "message_id": message_id}
