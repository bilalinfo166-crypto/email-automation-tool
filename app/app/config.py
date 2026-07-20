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
