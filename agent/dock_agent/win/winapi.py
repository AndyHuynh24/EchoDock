"""Small Windows helpers the Windows agent shares: windows and the apps they
belong to, bringing a window to the front, keys, the clipboard, screens and
idle time. (Win32 through pywin32 and ctypes.)

Coordinates are real screen pixels everywhere: the agent is "per-monitor DPI
aware" (uiautomation sets that when it loads), so window positions, UI
Automation rectangles, the mouse and screenshots all agree.
"""

import ctypes
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pythoncom
import win32api
import win32clipboard
import win32con
import win32gui
import win32process

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
FRAME_HOST = "applicationframehost.exe"  # hosts Store apps (Calculator, Settings…)

# What people call an app, by its program file (the file's own description
# is used for everything else, e.g. "Google Chrome").
NAMES = {
    "explorer": "File Explorer", "windowsterminal": "Terminal", "code": "Visual Studio Code",
    "msedge": "Microsoft Edge", "chrome": "Google Chrome", "firefox": "Firefox", "winword": "Microsoft Word",
    "excel": "Microsoft Excel", "powerpnt": "Microsoft PowerPoint", "outlook": "Microsoft Outlook",
    "olk": "Outlook", "onenote": "OneNote", "notepad": "Notepad", "mspaint": "Paint",
    "calculatorapp": "Calculator", "systemsettings": "Settings", "rstudio": "RStudio",
    "acrobat": "Adobe Acrobat", "acrord32": "Adobe Acrobat Reader", "ms-teams": "Microsoft Teams",
    "spotify": "Spotify", "discord": "Discord", "slack": "Slack", "zoom": "Zoom", "capcut": "CapCut",
}


def com_ready() -> None:
    """COM (Windows Search, shortcuts, File Explorer windows) must be started once per thread."""
    try:
        pythoncom.CoInitialize()
    except pythoncom.com_error:
        pass


# ---- Windows and apps ----

def foreground() -> int:
    return win32gui.GetForegroundWindow()


def title(hwnd: int) -> str:
    try:
        return win32gui.GetWindowText(hwnd)
    except win32gui.error:
        return ""


def _raw_pid(hwnd: int) -> int:
    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except win32gui.error:
        return 0


_exe_cache: dict[int, str] = {}


def exe_path(pid: int) -> str:
    """The program file of a process, e.g. C:\\Program Files\\…\\chrome.exe ("" if hidden from us)."""
    if pid in _exe_cache:
        return _exe_cache[pid]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    path = ""
    if handle:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            path = buffer.value
        kernel32.CloseHandle(handle)
    if len(_exe_cache) > 500:
        _exe_cache.clear()
    _exe_cache[pid] = path
    return path


def window_pid(hwnd: int) -> int:
    """The process of the app that owns this window. Store apps all run inside
    one "frame host" process, so for those it's the app's own process inside it."""
    pid = _raw_pid(hwnd)
    if not exe_path(pid).lower().endswith(FRAME_HOST):
        return pid
    inner = []

    def child(handle, _):
        if win32gui.GetClassName(handle) == "Windows.UI.Core.CoreWindow":
            inner.append(_raw_pid(handle))
        return True

    try:
        win32gui.EnumChildWindows(hwnd, child, None)
    except win32gui.error:
        pass
    return next((p for p in inner if p and p != pid), pid)


def _description(path: str) -> str:
    try:
        language, codepage = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")[0]
        text = win32api.GetFileVersionInfo(path, f"\\StringFileInfo\\{language:04x}{codepage:04x}\\FileDescription")
        return str(text or "").strip()
    except Exception:
        return ""


_name_cache: dict[str, str] = {}


def app_name(pid: int, hwnd: int = 0) -> str:
    """What people call the app: "Google Chrome", "File Explorer", "Calculator"."""
    path = exe_path(pid)
    stem = Path(path).stem.lower() if path else ""
    if stem in NAMES:
        return NAMES[stem]
    if not path or path.lower().endswith(FRAME_HOST):
        return title(hwnd) or "This app"
    if path not in _name_cache:
        described = _description(path)
        # (Some programs describe themselves at length: keep it short.)
        _name_cache[path] = described if described and len(described) <= 40 else Path(path).stem
    return _name_cache[path]


# Windows' own shell: the taskbar, the desktop, Start and search. Clicking Dock's
# tray icon puts the taskbar in front, but the user is still "in" their app.
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "NotifyIconOverflowWindow",
                 "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow"}
SHELL_PROGRAMS = {"startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe", "shellexperiencehost.exe",
                  "lockapp.exe", "textinputhost.exe"}


def is_shell(hwnd: int) -> bool:
    try:
        if win32gui.GetClassName(hwnd) in SHELL_CLASSES:
            return True
    except win32gui.error:
        return True
    return Path(exe_path(_raw_pid(hwnd))).name.lower() in SHELL_PROGRAMS


def _cloaked(hwnd: int) -> bool:
    """Windows on another virtual desktop, or Store apps that are suspended, are "cloaked"."""
    value = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return value.value != 0


def is_app_window(hwnd: int) -> bool:
    """A normal window with a title, as in the taskbar (not tool windows or hidden ones)."""
    if not win32gui.IsWindowVisible(hwnd) or _cloaked(hwnd) or not title(hwnd) or is_shell(hwnd):
        return False
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if style & win32con.WS_EX_TOOLWINDOW:
        return False
    owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
    return not owner or bool(style & win32con.WS_EX_APPWINDOW)


def app_windows() -> list[int]:
    """The app windows on this desktop, front first (not Dock's own)."""
    found = []

    def each(hwnd, _):
        if is_app_window(hwnd) and _raw_pid(hwnd) != os.getpid():
            found.append(hwnd)
        return True

    win32gui.EnumWindows(each, None)
    return found


_last_window: dict[int, int] = {}  # pid -> the window last seen in front for that app


def remember(hwnd: int, pid: int) -> None:
    _last_window[pid] = hwnd


def window_of(pid: int) -> int:
    """The app's window to act on: the one last seen in front, else its front-most one."""
    hwnd = _last_window.get(pid)
    if hwnd and win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
        return hwnd
    return next((h for h in app_windows() if window_pid(h) == pid), 0)


def rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Where the window is on screen: (x, y, width, height), without the
    invisible borders Windows 10 and 11 put around windows."""
    box = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(box), ctypes.sizeof(box)) != 0:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except win32gui.error:
            return None
    else:
        left, top, right, bottom = box.left, box.top, box.right, box.bottom
    return (left, top, right - left, bottom - top) if right > left and bottom > top else None


def borders(hwnd: int) -> tuple[int, int, int, int]:
    """The invisible borders (left, top, right, bottom) between GetWindowRect and what you see."""
    try:
        outer = win32gui.GetWindowRect(hwnd)
    except win32gui.error:
        return 0, 0, 0, 0
    seen = rect(hwnd)
    if seen is None:
        return 0, 0, 0, 0
    return seen[0] - outer[0], seen[1] - outer[1], outer[2] - (seen[0] + seen[2]), outer[3] - (seen[1] + seen[3])


def bring_forward(hwnd: int) -> bool:
    """Bring a window to the front and give it the keyboard. Windows only lets
    the app in front hand over the front, so Dock briefly joins the front
    app's input (AttachThreadInput), the usual way to do this."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    front = foreground()
    if front == hwnd:
        return True
    mine = win32api.GetCurrentThreadId()
    theirs = win32process.GetWindowThreadProcessId(front)[0] if front else 0
    attached = bool(theirs) and theirs != mine and user32.AttachThreadInput(mine, theirs, True)
    try:
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except win32gui.error:
            pass
    finally:
        if attached:
            user32.AttachThreadInput(mine, theirs, False)
    for _ in range(20):
        if foreground() == hwnd:
            return True
        time.sleep(0.05)
    return foreground() == hwnd


# ---- Keys ----

EXTENDED = {win32con.VK_LEFT, win32con.VK_RIGHT, win32con.VK_UP, win32con.VK_DOWN, win32con.VK_HOME,
            win32con.VK_END, win32con.VK_PRIOR, win32con.VK_NEXT, win32con.VK_INSERT, win32con.VK_DELETE}


def keys(*codes: int) -> None:
    """Press a key combination, e.g. keys(VK_CONTROL, ord("V")): down in order, up in reverse."""
    for code in codes:
        win32api.keybd_event(code, 0, win32con.KEYEVENTF_EXTENDEDKEY if code in EXTENDED else 0, 0)
        time.sleep(0.01)
    for code in reversed(codes):
        flags = win32con.KEYEVENTF_KEYUP | (win32con.KEYEVENTF_EXTENDEDKEY if code in EXTENDED else 0)
        win32api.keybd_event(code, 0, flags, 0)
        time.sleep(0.01)


def any_key_down() -> bool:
    """Is a key or mouse button held right now?"""
    return any(win32api.GetAsyncKeyState(code) & 0x8000 for code in range(0x01, 0xFF) if code not in (0x07, 0x0A, 0x0B))


def idle_seconds() -> float:
    return (win32api.GetTickCount() - win32api.GetLastInputInfo()) / 1000


# ---- Clipboard ----

_clipboard_lock = threading.Lock()


def _open_clipboard() -> bool:
    for _ in range(20):  # another app may be using it for a moment
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(0.05)
    return False


def clipboard_number() -> int:
    """Changes every time anything is copied."""
    return user32.GetClipboardSequenceNumber()


def _kept_formats() -> list[int]:
    return [win32con.CF_UNICODETEXT, win32con.CF_DIB,
            win32clipboard.RegisterClipboardFormat("HTML Format"),
            win32clipboard.RegisterClipboardFormat("Rich Text Format")]


def save_clipboard() -> dict:
    """What's on the clipboard now (text, pictures, formatted text), to put back later."""
    saved = {}
    with _clipboard_lock:
        if not _open_clipboard():
            return saved
        try:
            for kind in _kept_formats():
                if win32clipboard.IsClipboardFormatAvailable(kind):
                    try:
                        saved[kind] = win32clipboard.GetClipboardData(kind)
                    except Exception:
                        pass
        finally:
            win32clipboard.CloseClipboard()
    return saved


def restore_clipboard(saved: dict) -> None:
    with _clipboard_lock:
        if not _open_clipboard():
            return
        try:
            win32clipboard.EmptyClipboard()
            for kind, data in saved.items():
                try:
                    win32clipboard.SetClipboardData(kind, data)
                except Exception:
                    pass
        finally:
            win32clipboard.CloseClipboard()


def clipboard_text() -> str:
    with _clipboard_lock:
        if not _open_clipboard():
            return ""
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or "")
            return ""
        finally:
            win32clipboard.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    with _clipboard_lock:
        if not _open_clipboard():
            return
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()


# ---- Screens ----

def screens() -> list[dict]:
    """Each screen: {"area": usable (x, y, w, h) without the taskbar, "full": the
    whole screen, "primary": bool}, the main screen first."""
    found = []
    for monitor, _, _ in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(monitor)
        (l, t, r, b), (wl, wt, wr, wb) = info["Monitor"], info["Work"]
        found.append({"full": (l, t, r - l, b - t), "area": (wl, wt, wr - wl, wb - wt), "primary": bool(info["Flags"] & 1)})
    found.sort(key=lambda s: not s["primary"])
    return found


def screen_of(point: tuple[float, float]) -> dict:
    for screen in screens():
        x, y, w, h = screen["full"]
        if x <= point[0] < x + w and y <= point[1] < y + h:
            return screen
    return screens()[0]


def scale() -> float:
    """How much bigger than normal things are drawn (1.5 at 150 %)."""
    try:
        return user32.GetDpiForSystem() / 96
    except Exception:
        return 1.0


# ---- Recent files (Windows keeps a shortcut for each file you open) ----

RECENT = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
_recent_cache: tuple[float, list[tuple[float, Path]]] = (0.0, [])


def recent_files(max_files: int = 300) -> list[tuple[float, Path]]:
    """(when it was opened, the file) for recently opened files, newest first. Cached for a minute."""
    global _recent_cache
    if time.time() - _recent_cache[0] < 60:
        return _recent_cache[1]
    com_ready()
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    links = sorted(RECENT.glob("*.lnk"), key=lambda p: p.stat().st_mtime, reverse=True)[:max_files] if RECENT.is_dir() else []
    found = []
    for link in links:
        try:
            target = Path(shell.CreateShortcut(str(link)).TargetPath)
        except Exception:
            continue
        if target.suffix and target.is_file():
            found.append((link.stat().st_mtime, target))
    _recent_cache = (time.time(), found)
    return found


def document_in_title(window_title: str) -> str:
    """The file a window shows, if its title names a file opened recently
    ("hw4.Rmd - RStudio", "Report.docx - Word")."""
    lowered = window_title.lower()
    for _, path in recent_files():
        if path.name.lower() in lowered or (len(path.stem) > 3 and path.stem.lower() in lowered.split(" - ")[0]):
            return str(path)
    return ""
