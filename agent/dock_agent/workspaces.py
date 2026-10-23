"""Saved workspaces on macOS: apps, documents, browser tabs, Finder folders and window
positions on the current Space. Stored in ~/.dock/workspaces/.
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from AppKit import NSApplicationActivationPolicyRegular, NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from Quartz import CGPoint, CGSize

from dock_agent.menus import _get, _rect
from dock_agent.workspaces_common import WORKSPACE_DIR, WorkspaceError, _load, _norm, bare, list_all  # noqa: F401

SETTLE_SECONDS = 2.5

TABS_SCRIPTS = {
    "Google Chrome": 'tell application "Google Chrome" to get URL of tabs of windows',
    "Safari": 'tell application "Safari" to get URL of tabs of windows',
}
FINDER_SCRIPT = """
tell application "Finder"
    set found to {}
    repeat with shown in (get target of every Finder window)
        try
            set end of found to POSIX path of (shown as alias)
        end try
    end repeat
    return found
end tell
"""


def _applescript_strings(script: str) -> list[str]:
    """Run AppleScript and return the strings in its result."""
    try:
        output = subprocess.run(["osascript", "-s", "s", "-e", script], capture_output=True, text=True, timeout=8).stdout
    except subprocess.TimeoutExpired:
        return []
    return re.findall(r'"((?:[^"\\]|\\.)*)"', output)


def _windows(pid: int) -> list[dict]:
    windows = []
    for window in _get(AXUIElementCreateApplication(pid), "AXWindows") or []:
        rect = _rect(window)
        if rect is None or _get(window, "AXMinimized"):
            continue
        document = _get(window, "AXDocument")
        path = unquote(urlparse(str(document)).path) if document else ""
        windows.append({"title": str(_get(window, "AXTitle") or ""), "document": path, "rect": rect})
    return windows


def save(name: str) -> dict:
    apps = []
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.activationPolicy() != NSApplicationActivationPolicyRegular or app.isHidden():
            continue
        if app.processIdentifier() == os.getpid():
            continue
        windows = _windows(app.processIdentifier())
        if not windows:
            continue
        app_name = str(app.localizedName())
        entry = {"app": app_name, "path": str(app.bundleURL().path()), "windows": windows}
        if app_name in TABS_SCRIPTS:
            entry["urls"] = _applescript_strings(TABS_SCRIPTS[app_name])
        if app_name == "Finder":
            entry["folders"] = _applescript_strings(FINDER_SCRIPT)
        apps.append(entry)
    if not apps:
        raise WorkspaceError("I don't see any open windows to save.")

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    name = bare(name)
    workspace = {"name": name, "saved": datetime.now().isoformat(timespec="minutes"), "apps": apps}
    (WORKSPACE_DIR / f"{_norm(name) or 'workspace'}.json").write_text(json.dumps(workspace, indent=2))
    return {
        "name": name,
        "apps": [a["app"] for a in apps],
        "documents": sum(1 for a in apps for w in a["windows"] if w["document"]),
        "tabs": sum(len(a.get("urls", [])) for a in apps),
    }


def _folders_from_titles(windows: list[dict]) -> list[str]:
    """Older workspaces: a Finder window's title is its folder name."""
    home = Path.home()
    folders = []
    for window in windows:
        title = window["title"]
        if not title:
            continue
        for folder in (home if title == home.name else None, home / title):
            if folder is not None and folder.is_dir():
                folders.append(str(folder))
                break
    return folders


def _reopen(app: dict) -> None:
    documents = [w["document"] for w in app["windows"] if w["document"] and Path(w["document"]).exists()]
    if app["app"] == "Finder":
        folders = app.get("folders") or _folders_from_titles(app["windows"])
        for folder in folders:
            if Path(folder).exists():
                subprocess.run(["open", folder])
        if not folders:
            subprocess.run(["open", "-a", "Finder"])
    elif app.get("urls"):
        # Don't reopen tabs that are already open.
        is_running = any(a.localizedName() == app["app"] for a in NSWorkspace.sharedWorkspace().runningApplications())
        already_open = set(_applescript_strings(TABS_SCRIPTS[app["app"]])) if is_running else set()
        missing = [url for url in app["urls"] if url not in already_open]
        subprocess.run(["open", "-a", app["path"], *missing])
    else:
        subprocess.run(["open", "-a", app["path"], *documents])


def _move_windows(app: dict) -> None:
    running = [a for a in NSWorkspace.sharedWorkspace().runningApplications()
               if a.bundleURL() and str(a.bundleURL().path()) == app["path"]]
    if not running:
        return
    current = list(_get(AXUIElementCreateApplication(running[0].processIdentifier()), "AXWindows") or [])

    def pick(saved):
        # Match by document, then title, then any remaining window.
        for test in (
            lambda w: saved["document"] and _windows_document(w) == saved["document"],
            lambda w: saved["title"] and str(_get(w, "AXTitle") or "") == saved["title"],
            lambda w: True,
        ):
            for window in current:
                if test(window):
                    current.remove(window)
                    return window
        return None

    for saved in app["windows"]:
        window = pick(saved)
        if window is None:
            break
        x, y, w, h = saved["rect"]
        AXUIElementSetAttributeValue(window, "AXPosition", AXValueCreate(kAXValueCGPointType, CGPoint(x, y)))
        AXUIElementSetAttributeValue(window, "AXSize", AXValueCreate(kAXValueCGSizeType, CGSize(w, h)))


def _windows_document(window) -> str:
    document = _get(window, "AXDocument")
    return unquote(urlparse(str(document)).path) if document else ""


def open_workspace(name: str) -> dict:
    workspace = _load(name)
    for app in workspace["apps"]:
        _reopen(app)
    time.sleep(SETTLE_SECONDS)
    for app in workspace["apps"]:
        try:
            _move_windows(app)
        except Exception as e:
            print(f"Couldn't move {app['app']} windows: {e!r}")
    return {"name": bare(workspace["name"]), "apps": [a["app"] for a in workspace["apps"]]}
