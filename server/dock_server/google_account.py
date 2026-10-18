"""Sign in with Google: one sign-in connects both Google Calendar and Gmail.

"Sign in with Google" in Dock's window opens Google's page in the browser;
the user picks their account and clicks Allow (Google lets them untick
Calendar or Gmail there). The sign-in is kept on this computer only, in
.data/google_token.json, with which permissions were given and the account's
address in .data/google_account.json. "Sign out" removes both.

Needs Dock registered once in Google Cloud: google_oauth_client.json next to
the server folder (see docs/GOOGLE-CALENDAR.md). Until Google reviews Dock,
users see "Google hasn't verified this app" once.
"""

import json
import os
import threading
from pathlib import Path

from dock_server.state import DATA_DIR

CLIENT_FILE = Path(__file__).resolve().parent.parent / "google_oauth_client.json"
TOKEN_FILE = DATA_DIR / "google_token.json"
ACCOUNT_FILE = DATA_DIR / "google_account.json"
OLD_MAIL_TOKEN = DATA_DIR / "google_mail_token.json"  # (from when Gmail had its own sign-in)

CALENDAR_READ = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_ADD = "https://www.googleapis.com/auth/calendar.events"  # to-dos and reminders, only when the user says so
MAIL = "https://mail.google.com/"  # Gmail through IMAP, which Dock uses to read and (after a yes) file or trash email
SCOPES = [CALENDAR_READ, CALENDAR_ADD, MAIL]

_lock = threading.Lock()


def ready() -> bool:
    """True if Dock is registered with Google, so the button can work."""
    return CLIENT_FILE.exists()


def _account() -> dict:
    return json.loads(ACCOUNT_FILE.read_text()) if ACCOUNT_FILE.exists() and TOKEN_FILE.exists() else {}


def address() -> str:
    """The signed-in Google account, or ""."""
    return _account().get("address", "")


def has(scope: str) -> bool:
    """Did the user allow this (Calendar, adding events, Gmail)?"""
    return scope in _account().get("scopes", [])


def sign_in() -> dict:
    """Open Google's sign-in page in the browser and wait for the user (up to
    5 minutes). Returns {"address", "calendar", "mail"}. Blocks: run it in a thread."""
    from google.auth.transport.requests import AuthorizedSession
    from google_auth_oauthlib.flow import InstalledAppFlow
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"  # (the user may untick Calendar or Gmail: that's fine)
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    credentials = flow.run_local_server(
        port=0, open_browser=True, timeout_seconds=300,
        success_message="Dock is connected to your Google account. You can close this tab.")
    granted = credentials.granted_scopes or SCOPES
    granted = granted.split() if isinstance(granted, str) else list(granted)
    session = AuthorizedSession(credentials)
    if MAIL in granted:
        found = session.get("https://gmail.googleapis.com/gmail/v1/users/me/profile", timeout=15).json().get("emailAddress", "")
    else:  # (the main calendar's id is the account's address)
        found = session.get("https://www.googleapis.com/calendar/v3/calendars/primary", timeout=15).json().get("id", "")
    with _lock:
        DATA_DIR.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(credentials.to_json())
        TOKEN_FILE.chmod(0o600)
        ACCOUNT_FILE.write_text(json.dumps({"address": found, "scopes": granted}, indent=2))
        OLD_MAIL_TOKEN.unlink(missing_ok=True)
    return {"address": found, "calendar": CALENDAR_READ in granted, "mail": MAIL in granted}


def credentials():
    """The signed-in credentials, refreshed if they've expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    with _lock:
        # (Only the permissions that were given: asking a refresh for more fails.)
        loaded = Credentials.from_authorized_user_file(str(TOKEN_FILE), _account().get("scopes") or SCOPES)
        if not loaded.valid and loaded.refresh_token:
            loaded.refresh(Request())
            TOKEN_FILE.write_text(loaded.to_json())
        return loaded


def sign_out() -> None:
    with _lock:
        for path in (TOKEN_FILE, ACCOUNT_FILE, OLD_MAIL_TOKEN):
            path.unlink(missing_ok=True)
