"""Encrypt / decrypt secrets (OAuth tokens, app passwords) before storing them."""
from cryptography.fernet import Fernet
from .config import settings

_fernet = Fernet(settings.FERNET_KEY.encode())


def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
