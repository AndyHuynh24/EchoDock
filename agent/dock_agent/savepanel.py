"""Detects macOS Save dialogs and switches them to the suggested folder.

Polls the front app once a second for the "save-panel" element. Folder switching
uses Go to Folder via System Events, since sandboxed apps run the panel out of process.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

from AppKit import NSRunningApplication
from ApplicationServices import AXUIElementCreateApplication, AXUIElementPerformAction, AXUIElementSetAttributeValue

from dock_agent import link, menus, overlay, tidy
from dock_agent.files import HOME

CHECK_SECONDS = 1
KEY_RETURN, KEY_ESCAPE = 36, 53
SKIP_ROLES = ("AXOutline", "AXBrowser", "AXTable", "AXList")

_open = None  # {"pid", "file", "app", "where"}
_switching = False


class SavePanelError(Exception):
    pass


def _find(element, identifier: str, depth: int = 0):
    """Child element with this Accessibility identifier."""
    if menus._get(element, "AXIdentifier") == identifier:
        return element
    if depth >= 6:
        return None
    for child in menus._get(element, "AXChildren") or []:
        if menus._get(child, "AXRole") not in SKIP_ROLES:
            found = _find(child, identifier, depth + 1)
            if found is not None:
                return found
    return None


def _panel(pid: int):
    """The app's open Save dialog, or None."""
    for window in menus._get(AXUIElementCreateApplication(pid), "AXWindows") or []:
        if menus._get(window, "AXIdentifier") == "save-panel":
            return window
        for child in menus._get(window, "AXChildren") or []:
            if menus._get(child, "AXIdentifier") == "save-panel":
                return child
    return None


def start() -> None:
    threading.Thread(target=_watch, daemon=True).start()


def _where(panel) -> str:
    """The folder selected in the dialog."""
    return str(menus._get(_find(panel, "where popup"), "AXValue") or "")


def _watch() -> None:
    """Report each Save dialog once its file name settles, and report folder or app changes."""
    global _open
    last_name = ""
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            app, pid = menus.front_app()
            panel = _panel(pid) if menus.check_permission() else None
            if panel is None:
                if _open is not None and _panel(_open["pid"]) is None:
                    link.send_event("save_panel_closed", file=_open["file"])
                    _open = None
                elif _open is not None and not _open.get("left"):
                    _open["left"] = True
                    link.send_event("save_panel_left", file=_open["file"])
                continue
            name = str(menus._get(_find(panel, "saveAsNameTextField"), "AXValue") or "")
            stable, last_name = name == last_name, name
            if not name or name.startswith("Untitled") or not stable:
                continue
            if _open is not None and _open["pid"] == pid and _open["file"] == name:
                where = _where(panel)
                if where and where != _open["where"] and not _switching:
                    _open["where"] = where
                    link.send_event("save_panel_folder_changed", file=name, where=where)
                continue
            _open = {"pid": pid, "file": name, "app": app, "where": _where(panel)}
            window_title, document = menus.front_window(pid)
            # Folder of the source document (exports usually go next to it).
            home = os.path.expanduser("~")
            document_folder = os.path.relpath(os.path.dirname(document), home) if document.startswith(home + "/") else ""
            link.send_event("save_panel", app=app, file=name, window_title=window_title, folders=tidy._folders(),
                            document_folder=document_folder)
        except Exception as e:
            print(f"Save window check failed: {e!r}")


def _system_events(command: str, text: str = "") -> None:
    """Run one System Events command; text is passed as an argument."""
    script = ["on run argv", f'tell application "System Events" to {command}', "end run"]
    try:
        subprocess.run(["osascript", *sum((["-e", line] for line in script), []), text],
                       capture_output=True, timeout=10, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise SavePanelError("I couldn't type into the Save window. Dock may need permission to control System Events.")


def _type(text: str) -> None:
    _system_events("keystroke (item 1 of argv)", text)


def _key(code: int) -> None:
    _system_events(f"key code {code}")


def _wait_for(check, seconds: float = 2.0):
    end = time.time() + seconds
    while time.time() < end:
        found = check()
        if found:
            return found
        time.sleep(0.1)
    return None


def _panel_app() -> int:
    """The app with the reported Save dialog, else the front app."""
    return _open["pid"] if _open is not None else menus.front_app()[1]


def point(label: str) -> dict:
    """Point at the dialog's Where menu."""
    panel = _panel(_panel_app())
    where = _find(panel, "where popup") if panel is not None else None
    rect = menus._rect(where) if where is not None else None
    if rect:
        overlay.show(rect, label)
    return {"shown": bool(rect)}


def save_in(folder: str, new_folder: bool = False, press_save: bool = True) -> dict:
    """Switch the open Save dialog to `folder` (relative to home) and click Save."""
    global _switching
    _switching = True
    try:
        return _save_in(folder, new_folder, press_save)
    finally:
        panel = _panel(_open["pid"]) if _open is not None else None
        if panel is not None:
            _open["where"] = _where(panel)  # don't report our own change
        _switching = False


def _save_in(folder: str, new_folder: bool, press_save: bool) -> dict:
    pid = _panel_app()
    if _panel(pid) is None:
        raise SavePanelError("There's no Save window open right now.")
    target = tidy._destination(folder, new_folder)
    overlay.hide()
    # Keys go to the front app, so activate the dialog's app.
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None and menus.front_app()[1] != pid:
        app.activateWithOptions_(0)
        if not _wait_for(lambda: menus.front_app()[1] == pid):
            raise SavePanelError("I couldn't bring the Save window to the front.")
        time.sleep(0.3)

    _system_events('keystroke "g" using {command down, shift down}')
    field = _wait_for(lambda: _find(_panel(pid), "PathTextField"))
    if field is None:
        raise SavePanelError("The Save window didn't open Go to Folder.")
    time.sleep(0.4)  # wait for the sheet, or keys get lost
    path = "~/" + str(target.relative_to(HOME)) if target.is_relative_to(HOME) else str(target)
    for _ in range(3):
        AXUIElementSetAttributeValue(field, "AXFocused", True)
        AXUIElementSetAttributeValue(field, "AXValue", "")
        time.sleep(0.1)
        _type(path)
        if _wait_for(lambda: str(menus._get(field, "AXValue") or "").rstrip("/") == path, 1.0):
            break
    else:
        _key(KEY_ESCAPE)
        raise SavePanelError("I couldn't type the folder into the Save window.")
    time.sleep(0.4)
    _key(KEY_RETURN)

    def switched():
        current = _panel(pid)
        if current is None or _find(current, "PathTextField") is not None:
            return None
        where = str(menus._get(_find(current, "where popup"), "AXValue") or "")
        return current if Path(target).name in where else None

    panel = _wait_for(switched)
    if panel is None:
        raise SavePanelError(f"I couldn't switch the Save window to {target.name}.")
    name = str(menus._get(_find(panel, "saveAsNameTextField"), "AXValue") or "")
    if press_save:
        save = _find(panel, "OKButton")
        if save is None:
            raise SavePanelError("I couldn't find the Save button.")
        AXUIElementPerformAction(save, "AXPress")
    return {"file": name, "to": str(target.relative_to(HOME)), "saved": press_save}
