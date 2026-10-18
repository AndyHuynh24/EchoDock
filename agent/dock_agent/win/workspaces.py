"""Saved workspaces on Windows: "remember this workspace as Study", then later
"open my Study workspace" (the same answers as dock_agent/workspaces.py).

Saving records, for every app window on this desktop: the program, where
the window is (and whether it's maximized), the file it shows (when the
window title names a recently opened file), File Explorer folders, and the
page each browser window shows (Windows only lets Dock see a browser's
current tab, not all of them). Opening reopens all of that and moves the
windows back. Saved in ~/.dock/workspaces/, like on the Mac, so the names
are shared with workspaces.py (bare, list_all, _load).
"""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import uiautomation as auto
import win32con
import win32gui

from dock_agent.win import uia, winapi
from dock_agent.workspaces_common import WORKSPACE_DIR, WorkspaceError, _load, _norm, bare, list_all

SETTLE_SECONDS = 3.0  # time for reopened apps to show their windows
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}
ADDRESS_NAMES = ("address and search bar", "search or enter address", "search with google or enter address", "address")
CREATE_NO_WINDOW = 0x08000000

__all__ = ["WorkspaceError", "bare", "list_all", "save", "open_workspace"]


def _explorer_folders() -> dict[int, str]:
    """Window -> the folder each File Explorer window shows."""
    winapi.com_ready()
    import win32com.client
    folders = {}
    try:
        for window in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                path = window.Document.Folder.Self.Path
                if path and Path(path).exists():
                    folders[int(window.HWND)] = path
            except Exception:
                continue
    except Exception as e:
        print(f"Couldn't read the File Explorer windows: {e!r}")
    return folders


def _browser_url(hwnd: int) -> str:
    """The page a browser window shows, from its address bar."""
    window = uia.window(hwnd)
    if window is None:
        return ""
    for part in uia.find_all(window, max_seconds=1.0):
        if part.type == auto.ControlType.EditControl and part.name.lower() in ADDRESS_NAMES:
            control = part.control()
            value = uia.pattern(control, "ValuePattern") if control is not None else None
            try:
                url = str(value.Value) if value is not None else ""
            except Exception:
                url = ""
            if url and "://" not in url and "." in url.split("/")[0]:
                url = "https://" + url  # (browsers hide "https://")
            return url if url.startswith(("http://", "https://")) else ""
    return ""


def _placement(hwnd: int) -> dict:
    show = win32gui.GetWindowPlacement(hwnd)[1]
    return {"rect": winapi.rect(hwnd), "maximized": show == win32con.SW_SHOWMAXIMIZED}


def save(name: str) -> dict:
    folders = _explorer_folders()
    by_app: dict[str, dict] = {}
    for hwnd in winapi.app_windows():
        if win32gui.IsIconic(hwnd):
            continue
        pid = winapi.window_pid(hwnd)
        program = winapi.exe_path(pid)
        app_name = winapi.app_name(pid, hwnd)
        if not program or program.lower().endswith(winapi.FRAME_HOST):
            continue  # (Store apps can't be reopened this way)
        entry = by_app.setdefault(program, {"app": app_name, "path": program, "windows": []})
        window_title = winapi.title(hwnd)
        window = {"title": window_title, "document": winapi.document_in_title(window_title), **_placement(hwnd)}
        if Path(program).name.lower() == "explorer.exe":
            window["folder"] = folders.get(hwnd, "")
        if Path(program).name.lower() in BROWSERS:
            window["url"] = _browser_url(hwnd)
        entry["windows"].append(window)
    entries = [e for e in by_app.values() if e["windows"]]
    if not entries:
        raise WorkspaceError("I don't see any open windows to save.")
    for entry in entries:
        entry["urls"] = [w["url"] for w in entry["windows"] if w.get("url")]
        entry["folders"] = [w["folder"] for w in entry["windows"] if w.get("folder")]
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    name = bare(name)
    workspace = {"name": name, "saved": datetime.now().isoformat(timespec="minutes"), "apps": entries, "system": "windows"}
    (WORKSPACE_DIR / f"{_norm(name) or 'workspace'}.json").write_text(json.dumps(workspace, indent=2))
    return {
        "name": name,
        "apps": [e["app"] for e in entries],
        "documents": sum(1 for e in entries for w in e["windows"] if w["document"]),
        "tabs": sum(len(e["urls"]) for e in entries),
    }


def _folders_from_titles(windows: list[dict]) -> list[str]:
    """If File Explorer's folders weren't saved: a window's title is its folder's
    name ("Downloads", or "Downloads - File Explorer")."""
    home = Path.home()
    folders = []
    for window in windows:
        title = window["title"].removesuffix(" - File Explorer").strip()
        for folder in ((home if title == home.name else None), (home / title if title else None)):
            if folder is not None and folder.is_dir():
                folders.append(str(folder))
                break
    return folders


def _reopen(app: dict, open_before: set[int]) -> None:
    program = app["path"]
    name = Path(program).name.lower()
    if name == "explorer.exe":
        folders = app.get("folders") or _folders_from_titles(app["windows"])
        for folder in folders:
            if Path(folder).exists():
                os.startfile(folder)
        if not folders:
            subprocess.Popen(["explorer"], creationflags=CREATE_NO_WINDOW)
        return
    if name in BROWSERS and app.get("urls"):
        subprocess.Popen([program, *app["urls"]], creationflags=CREATE_NO_WINDOW)
        return
    documents = [w["document"] for w in app["windows"] if w.get("document") and Path(w["document"]).exists()]
    for document in documents:
        os.startfile(document)
    already = any(winapi.exe_path(winapi.window_pid(h)).lower() == program.lower() for h in open_before)
    if not documents and not already and Path(program).exists():
        subprocess.Popen([program], creationflags=CREATE_NO_WINDOW)


def _move_windows(app: dict) -> None:
    current = [h for h in winapi.app_windows() if winapi.exe_path(winapi.window_pid(h)).lower() == app["path"].lower()]

    def pick(saved):
        # Same title first, then whatever window of the app is left.
        for test in (lambda h: saved["title"] and winapi.title(h) == saved["title"],
                     lambda h: saved.get("document") and Path(saved["document"]).name in winapi.title(h),
                     lambda h: True):
            for hwnd in current:
                if test(hwnd):
                    current.remove(hwnd)
                    return hwnd
        return 0

    for saved in app["windows"]:
        hwnd = pick(saved)
        if not hwnd:
            break
        if saved.get("maximized"):
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        elif saved.get("rect"):
            from dock_agent.win.arrange import _move
            _move(hwnd, saved["rect"], maximize=False)


def open_workspace(name: str) -> dict:
    workspace = _load(name)
    open_before = set(winapi.app_windows())
    for app in workspace["apps"]:
        try:
            _reopen(app, open_before)
        except Exception as e:
            print(f"Couldn't reopen {app['app']}: {e!r}")
    time.sleep(SETTLE_SECONDS)
    for app in workspace["apps"]:
        try:
            _move_windows(app)
        except Exception as e:
            print(f"Couldn't move {app['app']} windows: {e!r}")
    return {"name": bare(workspace["name"]), "apps": [a["app"] for a in workspace["apps"]]}
