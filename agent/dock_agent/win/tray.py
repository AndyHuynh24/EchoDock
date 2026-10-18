"""Dock's icon in the Windows tray (by the clock), instead of the Mac's menu
bar face: click it to ask Dock (the chat box opens), right-click for the
menu: open Dock, add your phone, start at login, quit. It turns cyan while
Dock listens, and its tooltip shows the focus countdown. Through pystray.
"""

import os
import subprocess
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from dock_agent.win import bubble, hotkey

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "OneDock.vbs"
LOGIN_ITEM = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "OneDock.lnk"

_icon = None
_state = {"status": "Dock is starting…", "focus": ""}


def _face(listening: bool) -> Image.Image:
    """Two eyes and a smile on a round badge (readable on light and dark taskbars)."""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([2, 2, size - 2, size - 2], fill=(0, 202, 255, 255) if listening else (22, 35, 58, 255))
    ink = (11, 18, 32, 255) if listening else (255, 255, 255, 255)
    for x in (20, 38):
        draw.rounded_rectangle([x, 18, x + 7, 33], radius=3, fill=ink)
    draw.arc([16, 22, 48, 48], start=25, end=155, fill=ink, width=5)
    return image


def _title() -> str:
    text = f"Dock · {_state['focus']} left" if _state["focus"] else _state["status"]
    return f"{text}\nClick to ask, or press {hotkey.KEY_NAME}"[:127]


def _ask(icon, item) -> None:
    from dock_agent.win import talk  # (talk uses this module too)
    if talk.listening():  # clicked again: cancel
        talk.cancel()
    else:  # (be quiet if Dock is talking; otherwise open the chat box and listen)
        talk.tap()


def _quit(icon, item) -> None:
    """Stop everything: the server, this agent and the phone tunnel (started together by scripts/start.ps1)."""
    launcher = os.environ.get("DOCK_LAUNCHER_PID")
    if launcher:
        subprocess.run(["taskkill", "/PID", launcher, "/T", "/F"], capture_output=True)
    icon.stop()
    os._exit(0)


def _toggle_login(icon, item) -> None:
    set_start_at_login(not LOGIN_ITEM.exists())
    icon.update_menu()


def start() -> None:
    global _icon
    menu = pystray.Menu(
        pystray.MenuItem("Ask Dock", _ask, default=True),
        pystray.MenuItem(lambda item: _state["status"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Dock…", lambda icon, item: bubble.show_welcome()),
        pystray.MenuItem("Add your phone…", lambda icon, item: bubble.show_welcome("phone")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start Dock when I log in", _toggle_login, checked=lambda item: LOGIN_ITEM.exists()),
        pystray.MenuItem("Quit Dock", _quit),
    )
    _icon = pystray.Icon("OneDock", _face(False), _title(), menu)
    threading.Thread(target=_icon.run, daemon=True, name="tray").start()


def set_listening(on: bool) -> None:
    if _icon is not None:
        _icon.icon = _face(on)


def set_focus(text: str) -> None:
    _state["focus"] = text
    if _icon is not None:
        _icon.title = _title()


def set_status(text: str) -> None:
    _state["status"] = text
    if _icon is not None:
        _icon.title = _title()
        _icon.update_menu()


def apply_start_at_login(on: bool) -> None:
    set_start_at_login(on)
    if _icon is not None:
        _icon.update_menu()


def set_start_at_login(on: bool) -> None:
    """Start Dock at login: a shortcut to scripts/OneDock.vbs in the Startup folder."""
    if not on:
        LOGIN_ITEM.unlink(missing_ok=True)
        return
    from dock_agent.win.winapi import com_ready
    com_ready()
    import win32com.client
    LOGIN_ITEM.parent.mkdir(parents=True, exist_ok=True)
    shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(LOGIN_ITEM))
    shortcut.TargetPath = "wscript.exe"
    shortcut.Arguments = f'"{LAUNCHER}"'
    shortcut.WorkingDirectory = str(ROOT)
    shortcut.Description = "Start OneDock"
    shortcut.Save()
