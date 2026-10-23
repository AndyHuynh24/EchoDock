"""Open apps by spoken name on Windows, using the Start menu list (Get-StartApps)
and shell:AppsFolder.
"""

import difflib
import json
import re
import subprocess
import threading
import time

from dock_agent.win import winapi

REFRESH_SECONDS = 600
CREATE_NO_WINDOW = 0x08000000

# Common short names -> Start menu name.
ALIASES = {
    "vscode": ["Visual Studio Code"], "code": ["Visual Studio Code"],
    "chrome": ["Google Chrome"], "edge": ["Microsoft Edge"], "firefox": ["Firefox", "Mozilla Firefox"],
    "word": ["Word", "Microsoft Word"], "excel": ["Excel", "Microsoft Excel"],
    "powerpoint": ["PowerPoint", "Microsoft PowerPoint"], "outlook": ["Outlook (new)", "Outlook", "Microsoft Outlook"],
    "teams": ["Microsoft Teams", "Teams"], "onenote": ["OneNote"],
    "settings": ["Settings"], "systemsettings": ["Settings"], "controlpanel": ["Control Panel"],
    "explorer": ["File Explorer"], "fileexplorer": ["File Explorer"], "finder": ["File Explorer"],
    "terminal": ["Terminal", "Windows PowerShell"], "powershell": ["Windows PowerShell", "PowerShell"],
    "calculator": ["Calculator"], "notepad": ["Notepad"], "paint": ["Paint"], "photos": ["Photos"],
    "textedit": ["Notepad"], "preview": ["Photos"],
}

_apps: dict[str, str] = {}
_loaded_at = 0.0
_lock = threading.Lock()


class AppNotFound(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _load() -> None:
    global _apps, _loaded_at
    try:
        output = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=20, creationflags=CREATE_NO_WINDOW).stdout
        found = json.loads(output or "[]")
        found = [found] if isinstance(found, dict) else found
        apps = {}
        for app in found:
            name = str(app.get("Name") or "")
            if name and not re.search(r"\b(uninstall|readme|help|website|documentation|release notes)\b", name, re.I):
                apps.setdefault(name, str(app.get("AppID") or ""))
        with _lock:
            _apps, _loaded_at = apps, time.time()
    except Exception as e:
        print(f"Couldn't list the Start menu apps: {e!r}")


def prepare() -> None:
    """List apps in the background at startup."""
    threading.Thread(target=_load, daemon=True).start()


def installed_apps() -> dict[str, str]:
    if not _apps or time.time() - _loaded_at > REFRESH_SECONDS:
        if _apps:
            prepare()
        else:
            _load()
    with _lock:
        return dict(_apps)


def find_app(name: str) -> tuple[str, str] | None:
    """(Start menu name, app id) for a spoken name, or None."""
    apps = installed_apps()
    by_norm = {_norm(app): app for app in apps}
    target = _norm(name.lower().removesuffix(" app"))
    if not target:
        return None
    if target in ALIASES:
        alias = next((a for a in ALIASES[target] if a in apps), None)
        return (alias, apps[alias]) if alias else None
    if target in by_norm:
        best = by_norm[target]
    else:
        starts = [app for key, app in by_norm.items() if key.startswith(target)]
        word_starts = [app for app in apps if any(_norm(word).startswith(target) for word in app.split())]
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


def launch(app_id: str, *args: str) -> None:
    """Launch an app like the Start menu does, optionally with files or links."""
    if args and re.match(r"^[A-Za-z]:\\", app_id):
        subprocess.Popen([app_id, *args], creationflags=CREATE_NO_WINDOW)
        return
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])


def open_app(name: str, exact: bool = False) -> dict:
    """Open an app by spoken name. exact=True accepts only an exact name."""
    found = find_app(name)
    if exact and found and _norm(found[0]) != _norm(name):
        found = None
    if not found:
        raise AppNotFound(f"I couldn't find an app called {name}.")
    app, app_id = found
    launch(app_id)
    return {"app": app}


# ---- running apps ----

def open_app_names() -> list[str]:
    names = {winapi.app_name(winapi.window_pid(hwnd), hwnd) for hwnd in winapi.app_windows()}
    return sorted(n for n in names if n)


def open_windows_by_app() -> dict[str, list[int]]:
    """App name -> windows, front first."""
    found: dict[str, list[int]] = {}
    for hwnd in winapi.app_windows():
        found.setdefault(winapi.app_name(winapi.window_pid(hwnd), hwnd), []).append(hwnd)
    return found


def running_window(name: str) -> int:
    """Front window of the named app, or 0."""
    windows = open_windows_by_app()
    norm = {_norm(app): hwnds for app, hwnds in windows.items()}
    target = _norm(name)
    for key in [_norm(a) for a in ALIASES.get(target, [])] + [target]:
        if key in norm:
            return norm[key][0]
    starts = [key for key in norm if key.startswith(target) or any(_norm(w).startswith(target) for w in key.split())]
    if starts:
        return norm[min(starts, key=len)][0]
    close = difflib.get_close_matches(target, list(norm), n=1, cutoff=0.6)
    return norm[close[0]][0] if close else 0


def bring_app_forward(name: str) -> dict:
    """Bring an open app to the front (fuzzy name match)."""
    hwnd = running_window(name)
    if not hwnd:
        raise AppNotFound(f"{name} isn't open.")
    winapi.bring_forward(hwnd)
    time.sleep(0.2)
    return {"app": winapi.app_name(winapi.window_pid(hwnd), hwnd)}
