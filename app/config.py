"""Loads configuration from the .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./warmwire.db")
    GOOGLE_CLIENT_SECRETS = os.getenv("GOOGLE_CLIENT_SECRETS", "credentials.json")
    OAUTH_REDIRECT_URI = os.getenv(
        "OAUTH_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
    )
    FERNET_KEY = os.getenv("FERNET_KEY", "")
    SENDING_DOMAIN = os.getenv("SENDING_DOMAIN", "").strip().lower()
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")
    # Public base URL used inside emails for unsubscribe + open-tracking links.
    # For real recipients this MUST be a public address (deployed domain or an
    # ngrok tunnel), NOT 127.0.0.1 — otherwise the link points at the
    # recipient's own machine and does nothing. Defaults to localhost for local
    # testing. Set PUBLIC_URL in .env, e.g. PUBLIC_URL=https://mail.uplyncio.com
    PUBLIC_URL = os.getenv("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")

    # OAuth scopes: send email + read (read is used later for warmup)
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]


settings = Settings()

if not settings.FERNET_KEY:
    raise RuntimeError(
        "FERNET_KEY is missing. Generate one with:\n"
        '  python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"\n'
        "then add it to your .env file."
    )
