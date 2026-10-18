"""Save windows on Windows: suggest the folder while you're choosing where to
save (the same answers as dock_agent/savepanel.py on the Mac).

When any app shows the standard Windows "Save As" window (Chrome with "Ask
where to save each file", File > Save As in Notepad, Word, …), the server
gets the file name, and Dock suggests a folder on the phone and in the
bubble. "Save here" switches the Save window to that folder the way you could
by hand: type the folder into "File name" and press Enter (Windows then opens
that folder), put the file name back, and click Save.

Checked once a second, only in the window in front. The standard Save window
is a dialog (class "#32770") with a "File name" box (id 1001) and a Save
button (id 1); its address bar is a toolbar named "Address: …".
"""

import threading
import time

import uiautomation as auto
import win32con
import win32gui

from dock_agent import link, tidy
from dock_agent.files import HOME
from dock_agent.win import overlay, uia, winapi

CHECK_SECONDS = 1
SAVE_WORDS = ("save", "export", "download")

_open = None  # the Save window being shown: {"hwnd", "pid", "file", "app", "where"}
_switching = False


class SavePanelError(Exception):
    pass


def _parts(hwnd: int) -> dict | None:
    """The Save window's name box, Save button and address bar, if `hwnd` is one."""
    try:
        if win32gui.GetClassName(hwnd) != "#32770":
            return None
    except win32gui.error:
        return None
    window = uia.window(hwnd)
    if window is None:
        return None
    name_box = save_button = address = None
    for part in uia.find_all(window, max_seconds=1.0):
        if part.type == auto.ControlType.EditControl and part.automation_id == "1001" and name_box is None:
            name_box = part
        elif part.type == auto.ControlType.ButtonControl and part.automation_id == "1":
            save_button = part
        elif part.type == auto.ControlType.ToolBarControl and part.name.lower().startswith("address:"):
            address = part
    if name_box is None or save_button is None:
        return None
    if not any(word in save_button.name.lower() for word in SAVE_WORDS):
        return None  # an Open window, not a Save window
    return {"name": name_box, "save": save_button, "address": address}


def _value(found) -> str:
    control = found.control() if found is not None else None
    value = uia.pattern(control, "ValuePattern") if control is not None else None
    try:
        return str(value.Value or "") if value is not None else ""
    except Exception:
        return ""


def _where(parts: dict) -> str:
    """The folder the Save window is in (from its address bar, "Address: Documents\\school")."""
    address = parts.get("address")
    return address.name.split(":", 1)[1].strip() if address is not None else ""


def start() -> None:
    threading.Thread(target=_watch, daemon=True, name="save windows").start()


def _watch() -> None:
    """Announce each Save window once it shows a real file name (again if you
    type a new one, once you stop typing), and notice when you pick a folder
    yourself, switch away, or close it."""
    global _open
    uia.ready()
    last_name = ""
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            hwnd = winapi.foreground()
            parts = _parts(hwnd) if hwnd else None
            if parts is None:
                if _open is not None and not win32gui.IsWindow(_open["hwnd"]):
                    link.send_event("save_panel_closed", file=_open["file"])
                    _open = None
                elif _open is not None and not _open.get("left") and win32gui.IsWindow(_open["hwnd"]):
                    _open["left"] = True
                    link.send_event("save_panel_left", file=_open["file"])
                continue
            name = _value(parts["name"])
            stable, last_name = name == last_name, name
            if not name or name.lower().startswith("untitled") or not stable:
                continue
            if _open is not None and _open["hwnd"] == hwnd and _open["file"] == name:
                where = _where(parts)
                if where and where != _open["where"] and not _switching:
                    _open["where"] = where
                    link.send_event("save_panel_folder_changed", file=name, where=where)
                continue
            pid = winapi.window_pid(hwnd)
            owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
            app = winapi.app_name(pid, owner or hwnd)
            _open = {"hwnd": hwnd, "pid": pid, "file": name, "app": app, "where": _where(parts)}
            link.send_event("save_panel", app=app, file=name, window_title=winapi.title(owner) if owner else "",
                            folders=tidy._folders())
        except Exception as e:
            print(f"Save window check failed: {e!r}")


def point(label: str) -> dict:
    """Point at the Save window's address bar with Dock's suggestion."""
    parts = _parts(_open["hwnd"]) if _open is not None else None
    rect = (parts["address"] or parts["name"]).rect if parts is not None else None
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
        parts = _parts(_open["hwnd"]) if _open is not None and win32gui.IsWindow(_open["hwnd"]) else None
        if parts is not None:
            _open["where"] = _where(parts)  # so Dock's own switch isn't reported as yours
        _switching = False


def _wait_for(check, seconds: float = 3.0):
    end = time.time() + seconds
    while time.time() < end:
        found = check()
        if found:
            return found
        time.sleep(0.1)
    return None


def _save_in(folder: str, new_folder: bool, press_save: bool) -> dict:
    if _open is None or not win32gui.IsWindow(_open["hwnd"]):
        raise SavePanelError("There's no Save window open right now.")
    hwnd = _open["hwnd"]
    parts = _parts(hwnd)
    if parts is None:
        raise SavePanelError("There's no Save window open right now.")
    target = tidy._destination(folder, new_folder)  # checks it's one of your folders; may create it
    overlay.hide()
    if not winapi.bring_forward(hwnd):
        raise SavePanelError("I couldn't bring the Save window to the front.")
    name = _value(parts["name"]) or _open["file"]

    def set_name(text: str) -> bool:
        control = _parts(hwnd)["name"].control()
        value = uia.pattern(control, "ValuePattern") if control is not None else None
        if value is None:
            return False
        control.SetFocus()
        value.SetValue(text, waitTime=0)
        return True

    # Typing a folder into "File name" and pressing Enter opens that folder.
    if not set_name(str(target)):
        raise SavePanelError("I couldn't type the folder into the Save window.")
    time.sleep(0.2)
    winapi.keys(win32con.VK_RETURN)

    def switched():
        current = _parts(hwnd) if win32gui.IsWindow(hwnd) else None
        return current if current is not None and target.name.lower() in _where(current).lower() else None

    if _wait_for(switched) is None:
        raise SavePanelError(f"I couldn't switch the Save window to {target.name}.")
    set_name(name)
    time.sleep(0.2)
    if press_save:
        save = _parts(hwnd)["save"].control()
        if save is None or not uia.press(save):
            raise SavePanelError("I couldn't find the Save button.")
    to = str(target.relative_to(HOME)) if target.is_relative_to(HOME) else str(target)
    return {"file": name, "to": to.replace("\\", "/"), "saved": press_save}
