"""Open apps by spoken name ("VS Code" -> Visual Studio Code)."""

import difflib
import re
import subprocess
from pathlib import Path

APP_FOLDERS = [
    Path("/Applications"),
    Path("/Applications/Utilities"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
]

# Common short names.
ALIASES = {
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "teams": "Microsoft Teams",
    "settings": "System Settings",
    "systempreferences": "System Settings",
}


class AppNotFound(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def installed_apps() -> dict[str, Path]:
    apps = {}
    for folder in APP_FOLDERS:
        if folder.is_dir():
            for app in folder.glob("*.app"):
                apps.setdefault(app.stem, app)
    return apps


def find_app(name: str) -> tuple[str, Path] | None:
    apps = installed_apps()
    by_norm = {_norm(app): app for app in apps}
    target = _norm(name.lower().removesuffix(" app"))
    if not target:
        return None

    if target in ALIASES:
        alias = ALIASES[target]
        # Known alias but not installed: don't guess.
        return (alias, apps[alias]) if alias in apps else None
    if target in by_norm:
        best = by_norm[target]
    else:
        # Prefix matches per word, but "word" must not match "Passwords".
        starts = [app for key, app in by_norm.items() if key.startswith(target)]
        word_starts = [
            app for app in apps
            if any(_norm(word).startswith(target) for word in app.split())
        ]
        close = difflib.get_close_matches(target, by_norm, n=1, cutoff=0.82)
        if starts:
            best = min(starts, key=len)
        elif word_starts:
            best = min(word_starts, key=len)
        elif close:
            best = by_norm[close[0]]
        else:
            return None
    return best, apps[best]


def open_app(name: str, exact: bool = False) -> dict:
    """Open an app by spoken name. exact=True accepts only an exact name."""
    found = find_app(name)
    if exact and found and _norm(found[0]) != _norm(name):
        found = None
    if exact and not found:
        raise AppNotFound(f"I couldn't find an app called {name}.")
    if found:
        app, path = found
        subprocess.run(["open", "-a", str(path)], check=True)
        return {"app": app}
    # Fall back to macOS's own lookup.
    if subprocess.run(["open", "-a", name], capture_output=True).returncode == 0:
        return {"app": name}
    raise AppNotFound(f"I couldn't find an app called {name}.")
