"""Save windows: suggest the folder while you're choosing where to save.

When any app shows the standard macOS Save window (Chrome with "Ask where to
save each file", or File > Save in TextEdit, Word, …), the server gets the
file name, and Dock suggests a folder on the phone and next to the window.
Tapping "Save here" (or saying "save it there") switches the Save window to
that folder, the same way you would by hand (Command-Shift-G, type the
folder, Return), then clicks Save. The keys are typed through System Events:
in sandboxed apps like Safari the Save window runs in a separate macOS
process, and plain key events from Dock don't reach it.

Checked once a second, only in the app in front. Accessibility shows the
Save window as an element with the identifier "save-panel", inside the app's
window (a sheet) or as its own window.
"""

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
SKIP_ROLES = ("AXOutline", "AXBrowser", "AXTable", "AXList")  # file lists: big and not needed

_open = None  # the Save window being shown: {"pid", "file", "app", "where"}
_switching = False  # True while Dock itself is switching the Save window's folder


class SavePanelError(Exception):
    pass


def _find(element, identifier: str, depth: int = 0):
    """The element inside `element` with this Accessibility identifier."""
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
    """The app's open Save window, or None."""
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
    """The folder the Save window is set to (its "Where" menu)."""
    return str(menus._get(_find(panel, "where popup"), "AXValue") or "")


def _watch() -> None:
    """Announce each Save window once it shows a real file name. If you type a
    new name, it's announced again (once the name stops changing). If you pick
    a folder in it yourself or switch to another app, the server hears that too."""
    global _open
    last_name = ""  # the name at the previous check, to wait until typing stops
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
                    _open["left"] = True  # still open, but you switched to another app
                    link.send_event("save_panel_left", file=_open["file"])
                continue
            name = str(menus._get(_find(panel, "saveAsNameTextField"), "AXValue") or "")
            stable, last_name = name == last_name, name
            if not name or name.startswith("Untitled") or not stable:
                continue
            if _open is not None and _open["pid"] == pid and _open["file"] == name:
                where = _where(panel)  # already announced: only watch for a folder change
                if where and where != _open["where"] and not _switching:
                    _open["where"] = where
                    link.send_event("save_panel_folder_changed", file=name, where=where)
                continue
            _open = {"pid": pid, "file": name, "app": app, "where": _where(panel)}
            window_title, _ = menus.front_window(pid)
            link.send_event("save_panel", app=app, file=name, window_title=window_title, folders=tidy._folders())
        except Exception as e:
            print(f"Save window check failed: {e!r}")


def _system_events(command: str, text: str = "") -> None:
    """Run one System Events command, e.g. `keystroke (item 1 of argv)`. The text
    is passed as an argument, never pasted into the script."""
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
    """The app with the Save window Dock announced (else the app in front)."""
    return _open["pid"] if _open is not None else menus.front_app()[1]


def point(label: str) -> dict:
    """Point at the Save window's "Where" menu with Dock's suggestion."""
    panel = _panel(_panel_app())
    where = _find(panel, "where popup") if panel is not None else None
    rect = menus._rect(where) if where is not None else None
    if rect:
        overlay.show(rect, label)
    return {"shown": bool(rect)}


def save_in(folder: str, new_folder: bool = False, press_save: bool = True) -> dict:
    """Switch the open Save window to `folder` (relative to home), then click Save."""
    global _switching
    _switching = True
    try:
        return _save_in(folder, new_folder, press_save)
    finally:
        panel = _panel(_open["pid"]) if _open is not None else None
        if panel is not None:  # still open, e.g. if Save wasn't pressed
            _open["where"] = _where(panel)  # so Dock's own switch isn't reported as yours
        _switching = False


def _save_in(folder: str, new_folder: bool, press_save: bool) -> dict:
    pid = _panel_app()
    if _panel(pid) is None:
        raise SavePanelError("There's no Save window open right now.")
    target = tidy._destination(folder, new_folder)  # checks it's one of your folders; may create it
    overlay.hide()
    # The keys below go to the app in front, so bring the Save window's app forward.
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None and menus.front_app()[1] != pid:
        app.activateWithOptions_(0)
        if not _wait_for(lambda: menus.front_app()[1] == pid):
            raise SavePanelError("I couldn't bring the Save window to the front.")
        time.sleep(0.3)

    _system_events('keystroke "g" using {command down, shift down}')  # Go to Folder
    field = _wait_for(lambda: _find(_panel(pid), "PathTextField"))
    if field is None:
        raise SavePanelError("The Save window didn't open Go to Folder.")
    time.sleep(0.4)  # let the box finish appearing, or the first keys get lost
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
    time.sleep(0.4)  # it looks the folder up as you type
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
