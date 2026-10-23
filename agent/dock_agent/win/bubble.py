"""Dock's Windows UI: the bubble above the taskbar, the chat box, and the welcome window.

Shown with WebView2 via pywebview; the page posts the same messages as on the Mac
through window.pywebview.api.post().
"""

import json
import os
import queue
import threading
import time
from urllib.parse import quote

import webview
import win32con
import win32gui

from dock_agent.win import voice_out, winapi

WIDTH = 400
GAP = 12
TITLE = "OneDock bubble"

_window = None
_welcome = None
_hwnd = 0
_composing = False
_ready = False
_closed_at = 0.0  # when the chat box last closed itself
_calls: queue.Queue = queue.Queue()
on_focus = None
on_listen = None
on_cancel = None


def _server() -> str:
    return os.environ.get("DOCK_SERVER", "ws://localhost:8000").replace("ws", "http", 1).rstrip("/")


def _url() -> str:
    return f"{_server()}/?token={quote(os.environ.get('DOCK_TOKEN', ''))}&screen=mac"


class Api:
    """Messages from the page."""

    def post(self, data):
        try:
            _handle(dict(data or {}))
        except Exception as e:
            print(f"Bubble message failed: {e!r}")


def _handle(data: dict) -> None:
    global _ready
    if "show" in data:
        _place(bool(data["show"]), float(data.get("height") or 0))
    if "say" in data:
        voice_out.say(str(data["say"]), done=lambda: call("speechDone()"))
    if "focus" in data and on_focus:
        on_focus(str(data["focus"]))
    if data.get("listen") == "cancel":
        if on_cancel:
            on_cancel()
    elif data.get("listen") and on_listen:
        on_listen()
    if data.get("hush"):
        voice_out.stop()
    if data.get("sound") == "done":
        voice_out.done_sound()
    if data.get("compose") is False and _composing:
        compose(False)
    if data.get("settings"):
        compose(False)
        show_welcome()
    if data.get("ready"):
        _ready = True
        print("Bubble page ready")


def create() -> None:
    """Create the bubble (hidden until there's a card). Call before webview.start()."""
    global _window
    _window = webview.create_window(
        TITLE, _url(), js_api=Api(), width=WIDTH, height=120, min_size=(100, 20), resizable=False,
        frameless=True, easy_drag=False, shadow=False, on_top=True, focus=False, hidden=True,
        transparent=True, background_color="#0b1220")


def started() -> None:
    """Find the window once it exists and keep the page loaded."""
    global _hwnd
    for _ in range(100):
        _hwnd = win32gui.FindWindow(None, TITLE)
        if _hwnd:
            break
        time.sleep(0.1)
    threading.Thread(target=_run_calls, daemon=True, name="bubble calls").start()
    threading.Thread(target=_keep_loaded, daemon=True, name="bubble page").start()
    threading.Thread(target=_watch_keyboard, daemon=True, name="chat box").start()


def _keep_loaded() -> None:
    """Retry while the server is still starting."""
    while True:
        time.sleep(5)
        if not _ready and _window is not None:
            print("Bubble page didn't load yet; trying again")
            try:
                _window.load_url(_url())
            except Exception as e:
                print(f"Couldn't load the bubble page: {e!r}")
            time.sleep(5)


def _run_calls() -> None:
    while True:
        script = _calls.get()
        try:
            _window.evaluate_js(script)
        except Exception as e:
            print(f"Bubble script failed: {e!r}")


def _place(show: bool, height: float) -> None:
    if not _hwnd:
        return
    if not show or height <= 0:
        win32gui.ShowWindow(_hwnd, win32con.SW_HIDE)
        return
    scale = winapi.scale()
    x, y, w, h = winapi.screens()[0]["area"]
    width, height = round(WIDTH * scale), round(min(height * scale, h * 0.8))
    left, top = x + w - width - round(GAP * scale), y + h - height - round(GAP * scale)
    win32gui.SetWindowPos(_hwnd, win32con.HWND_TOPMOST, left, top, width, height,
                          win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)


def _focus_page() -> None:
    """Focus the page inside the window (WinForms keeps focus on the window)."""
    try:
        from System import Func, Type
        form = _window.native
        form.Invoke(Func[Type](lambda: form.browser.webview.Focus()))
    except Exception as e:
        print(f"Couldn't focus the chat box: {e!r}")


def compose(open_it: bool | None = None) -> None:
    """Open or close the chat box (None toggles)."""
    global _composing, _closed_at
    if open_it is None and not _composing and time.time() - _closed_at < 0.4:
        return
    if not _ready and not _composing:
        return
    _composing = (not _composing) if open_it is None else open_it
    call(f"macCompose({'true' if _composing else 'false'})")
    if _composing:
        for _ in range(20):
            if win32gui.IsWindowVisible(_hwnd):
                break
            time.sleep(0.05)
        winapi.bring_forward(_hwnd)
        _focus_page()
        return
    _closed_at = time.time()
    if winapi.foreground() == _hwnd:
        # Give the keyboard back to the user's app.
        from dock_agent.win import menus
        _, pid = menus.front_app()
        winapi.bring_forward(winapi.window_of(pid))
    win32gui.ShowWindow(_hwnd, win32con.SW_HIDE)
    call("tellBubble.last = null; tellBubble()")


def _watch_keyboard() -> None:
    """Close the chat box when focus moves elsewhere."""
    while True:
        time.sleep(0.2)
        if _composing and time.time() - _closed_at > 0.6 and _hwnd and winapi.foreground() != _hwnd:
            time.sleep(0.3)
            if _composing and winapi.foreground() != _hwnd:
                compose(False)


def just_closed() -> bool:
    """Whether the chat box just closed itself."""
    return not _composing and time.time() - _closed_at < 0.4


def has_keyboard() -> bool:
    return _composing and bool(_hwnd) and winapi.foreground() == _hwnd


def call(script: str) -> None:
    """Run JavaScript in the page. Safe from any thread."""
    _calls.put(script)


def listening(words: str | None) -> None:
    call(f"macListening({json.dumps(words)})")


def ask(text: str) -> None:
    call(f"macAsk({json.dumps(text)})")


def show_welcome(part: str = "") -> None:
    """Open the welcome window (part="phone" jumps to adding a phone)."""
    global _welcome
    url = f"{_server()}/setup?app=1" + (f"#{part}" if part else "")
    if _welcome is not None:
        try:
            _welcome.load_url(url)
            _welcome.show()
            _welcome.restore()
            return
        except Exception:
            _welcome = None
    _welcome = webview.create_window("Dock", url, width=720, height=820)

    def closed():
        global _welcome
        _welcome = None

    _welcome.events.closed += closed
