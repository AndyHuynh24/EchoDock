"""Google sign-in for Calendar and Gmail. Tokens are stored locally in .data/.

Requires google_oauth_client.json (see docs/GOOGLE-CALENDAR.md).
"""

import json
import os
import threading
from pathlib import Path

from dock_server.state import DATA_DIR

CLIENT_FILE = Path(__file__).resolve().parent.parent / "google_oauth_client.json"
TOKEN_FILE = DATA_DIR / "google_token.json"
ACCOUNT_FILE = DATA_DIR / "google_account.json"
OLD_MAIL_TOKEN = DATA_DIR / "google_mail_token.json"

CALENDAR_READ = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_ADD = "https://www.googleapis.com/auth/calendar.events"
MAIL = "https://mail.google.com/"
SCOPES = [CALENDAR_READ, CALENDAR_ADD, MAIL]

_lock = threading.Lock()


def ready() -> bool:
    return CLIENT_FILE.exists()


def _account() -> dict:
    return json.loads(ACCOUNT_FILE.read_text()) if ACCOUNT_FILE.exists() and TOKEN_FILE.exists() else {}


def address() -> str:
    return _account().get("address", "")


def has(scope: str) -> bool:
    return scope in _account().get("scopes", [])


def sign_in() -> dict:
    """Run the OAuth flow in the browser (blocking). Returns {"address", "calendar", "mail"}."""
    from google.auth.transport.requests import AuthorizedSession
    from google_auth_oauthlib.flow import InstalledAppFlow
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    credentials = flow.run_local_server(
        port=0, open_browser=True, timeout_seconds=300,
        success_message="Dock is connected to your Google account. You can close this tab.")
    granted = credentials.granted_scopes or SCOPES
    granted = granted.split() if isinstance(granted, str) else list(granted)
    session = AuthorizedSession(credentials)
    if MAIL in granted:
        found = session.get("https://gmail.googleapis.com/gmail/v1/users/me/profile", timeout=15).json().get("emailAddress", "")
    else:
        found = session.get("https://www.googleapis.com/calendar/v3/calendars/primary", timeout=15).json().get("id", "")
    with _lock:
        DATA_DIR.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(credentials.to_json())
        TOKEN_FILE.chmod(0o600)
        ACCOUNT_FILE.write_text(json.dumps({"address": found, "scopes": granted}, indent=2))
        OLD_MAIL_TOKEN.unlink(missing_ok=True)
    return {"address": found, "calendar": CALENDAR_READ in granted, "mail": MAIL in granted}


def credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    with _lock:
        loaded = Credentials.from_authorized_user_file(str(TOKEN_FILE), _account().get("scopes") or SCOPES)
        if not loaded.valid and loaded.refresh_token:
            loaded.refresh(Request())
            TOKEN_FILE.write_text(loaded.to_json())
        return loaded


def sign_out() -> None:
    with _lock:
        for path in (TOKEN_FILE, ACCOUNT_FILE, OLD_MAIL_TOKEN):
            path.unlink(missing_ok=True)
