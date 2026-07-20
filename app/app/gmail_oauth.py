"""Google OAuth flow: build the consent URL and exchange the code for tokens."""
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from .config import settings

# Remembers the PKCE code_verifier between the /start and /callback requests,
# keyed by the OAuth `state` value. Needed so token exchange doesn't fail with
# "Missing code verifier".
_pending_verifiers: dict[str, str] = {}


def _build_flow(state: str | None = None) -> Flow:
    return Flow.from_client_secrets_file(
        settings.GOOGLE_CLIENT_SECRETS,
        scopes=settings.SCOPES,
        redirect_uri=settings.OAUTH_REDIRECT_URI,
        state=state,
    )


def get_authorization_url() -> tuple[str, str]:
    """Returns (url, state). Send the user to `url`."""
    flow = _build_flow()
    url, state = flow.authorization_url(
        access_type="offline",        # so we get a refresh_token
        include_granted_scopes="true",
        prompt="consent",
    )
    # Save the PKCE verifier so the callback can complete the exchange.
    _pending_verifiers[state] = getattr(flow, "code_verifier", None)
    return url, state


def exchange_code(code: str, state: str | None = None) -> dict:
    """Turn the ?code=... from Google's redirect into stored credentials."""
    flow = _build_flow(state=state)
    # Restore the PKCE verifier that was generated in get_authorization_url.
    verifier = _pending_verifiers.pop(state, None)
    if verifier:
        flow.code_verifier = verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    return _creds_to_dict(creds)


def _creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or settings.SCOPES),
    }


def credentials_from_dict(d: dict) -> Credentials:
    """Rebuild a Credentials object and refresh it if the access token expired."""
    creds = Credentials(
        token=d.get("token"),
        refresh_token=d.get("refresh_token"),
        token_uri=d.get("token_uri"),
        client_id=d.get("client_id"),
        client_secret=d.get("client_secret"),
        scopes=d.get("scopes"),
    )
    if creds.refresh_token and (not creds.valid):
        creds.refresh(Request())
    return creds


def creds_to_json(d: dict) -> str:
    return json.dumps(d)


def creds_from_json(s: str) -> dict:
    return json.loads(s)
