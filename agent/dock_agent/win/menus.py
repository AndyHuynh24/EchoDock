"""Read and press the menu items of the app in front, on Windows (the same
answers as dock_agent/menus.py on the Mac).

Two kinds of menus:
- Classic menus (Notepad++, Paint.NET, RStudio, many older apps): Windows
  can list the whole menu without opening it, with each item's shortcut (the
  text after a tab: "Save\tCtrl+S"). Pressing one sends the app the same
  command a click would (WM_COMMAND).
- Newer menus (the new Notepad, File Explorer, VS Code, Office): only UI
  Automation sees them, and only while each menu is open. So Dock opens each
  one for a moment to read it (only when asked something, never just because
  you switched apps), and closes it again.

Apps with no menu bar (Chrome, Edge, most Store apps) have their buttons
listed by onscreen.py instead, like toolbar buttons on the Mac.
"""

import ctypes
import os
import re
import time
from ctypes import wintypes

import uiautomation as auto
import win32con
import win32gui

from dock_agent.win import uia, winapi

CACHE_SECONDS = 300
MENU_TIMEOUT = 1.0     # seconds to wait for an opened menu to show its items
SKIP_MENUS = {"system", "system menu bar", "minimize", "maximize", "close", "restore"}

user32 = ctypes.windll.user32
user32.GetMenu.restype = wintypes.HMENU
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = wintypes.UINT
user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.GetMenuState.restype = wintypes.UINT
user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
user32.GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT)]
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD)]

MF_BYPOSITION, MF_GRAYED, MF_DISABLED, MF_SEPARATOR, MF_POPUP = 0x400, 0x1, 0x2, 0x800, 0x10
NO_ID = 0xFFFFFFFF
WM_INITMENUPOPUP = 0x0117

_cache: dict[int, tuple[float, list[dict]]] = {}
_how: dict[tuple[int, tuple], dict] = {}   # (pid, path) -> {"kind": "classic", "hwnd", "id"} or {"kind": "uia"}
_last_other = None                          # the last app in front that wasn't Dock itself


class PermissionMissing(Exception):
    """(Never raised on Windows: UI Automation needs no permission.)"""


class MenuItemDisabled(Exception):
    pass


def check_permission(prompt: bool = False) -> bool:
    return True


# ---- Shortcuts as Windows shows them ("Ctrl+Shift+S") and as words ----

SPOKEN_KEYS = {"ctrl": "Control", "alt": "Alt", "shift": "Shift", "win": "Windows", "del": "Delete",
               "ins": "Insert", "esc": "Escape", "pgup": "Page Up", "pgdn": "Page Down", "bksp": "Backspace",
               "enter": "Enter", "tab": "Tab", "space": "Space", "plus": "Plus", "minus": "Minus",
               "up": "Up Arrow", "down": "Down Arrow", "left": "Left Arrow", "right": "Right Arrow"}


def spoken(shortcut: str) -> str:
    """ "Ctrl+Shift+S" -> "Control Shift S"."""
    if not shortcut:
        return ""
    parts = [p for p in re.split(r"\+(?=.)", shortcut.strip()) if p]
    return " ".join(SPOKEN_KEYS.get(p.strip().lower(), p.strip()) for p in parts)


def _split_label(text: str) -> tuple[str, str]:
    """ "&Save\tCtrl+S" -> ("Save", "Ctrl+S")."""
    title, _, shortcut = text.partition("\t")
    title = re.sub(r"&(.)", r"\1", title).strip()
    return title, shortcut.strip()


# ---- The app in front ----

def front_app() -> tuple[str, int]:
    """The app the user is working in. If Dock's own window is in front (its
    chat box or welcome window), that's the app they were using just before."""
    global _last_other
    hwnd = winapi.foreground()
    pid = winapi.window_pid(hwnd) if hwnd else 0
    if not hwnd or pid == os.getpid() or not pid or winapi.is_shell(hwnd):
        if _last_other is not None:
            return _last_other
        return "Windows", 0
    winapi.remember(hwnd, pid)
    _last_other = (winapi.app_name(pid, hwnd), pid)
    return _last_other


def front_window(pid: int) -> tuple[str, str]:
    """Title and (if Windows knows it) the file shown by the app's window."""
    hwnd = winapi.window_of(pid)
    window_title = winapi.title(hwnd) if hwnd else ""
    return window_title, winapi.document_in_title(window_title) if window_title else ""


# ---- Classic menus ----

def _menu_text(menu, position: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetMenuStringW(menu, position, buffer, len(buffer), MF_BYPOSITION)
    return buffer.value


def _prepare(hwnd: int, menu, position: int) -> None:
    """Tell the app its menu is about to open, so it fills in and greys out items as it would."""
    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(hwnd, WM_INITMENUPOPUP, menu, position, 0x2, 200, ctypes.byref(result))


def _walk_classic(hwnd: int, menu, path: list[str], items: list[dict], depth: int = 0) -> None:
    for position in range(max(0, user32.GetMenuItemCount(menu))):
        state = user32.GetMenuState(menu, position, MF_BYPOSITION)
        if state == NO_ID or state & MF_SEPARATOR:
            continue
        title, shortcut = _split_label(_menu_text(menu, position))
        if not title:
            continue  # (drawn by the app itself: no text to read)
        submenu = user32.GetSubMenu(menu, position)
        if submenu:
            if depth < 3:
                _prepare(hwnd, submenu, position)
                _walk_classic(hwnd, submenu, path + [title], items, depth + 1)
            continue
        command = user32.GetMenuItemID(menu, position)
        if command in (0, NO_ID):
            continue
        items.append({"path": path + [title], "shortcut": shortcut, "shortcut_spoken": spoken(shortcut),
                      "enabled": not state & (MF_GRAYED | MF_DISABLED), "_id": command})


def _classic(hwnd: int) -> list[dict]:
    menu = user32.GetMenu(hwnd)
    if not menu:
        return []
    items: list[dict] = []
    try:
        _walk_classic(hwnd, menu, [], items)
    except Exception as e:
        print(f"Couldn't read the classic menus: {e!r}")
    return items


# ---- Newer menus (UI Automation) ----

def _menu_bar(window):
    """The app's own menu bar (not the title bar's system menu)."""
    for found in uia.find_all(window, max_seconds=1.0):
        if found.type == auto.ControlType.MenuBarControl and found.name.lower() not in SKIP_MENUS:
            control = found.control()
            parent = control.GetParentControl() if control is not None else None
            if parent is not None and parent.ControlType == auto.ControlType.TitleBarControl:
                continue
            return control
    return None


def _open_menu_items(opened_from=None) -> list:
    """The items of the menu that just opened. Classic menus open as their own
    window on the desktop; newer ones under the item that opened them or
    inside the app's window (a "popup"), so look in all three places."""
    end = time.time() + MENU_TIMEOUT
    top = None
    try:
        top = opened_from.GetTopLevelControl() if opened_from is not None else None
    except Exception:
        pass
    while time.time() < end:
        menus = []
        for place in (opened_from, auto.GetRootControl()):
            if place is None:
                continue
            try:
                menus += [c for c in place.GetChildren() if c.ControlType == auto.ControlType.MenuControl]
            except Exception:
                pass
        if not menus and top is not None:
            menus = [f.control() for f in uia.find_all(top, max_seconds=0.5) if f.type == auto.ControlType.MenuControl]
        for menu in menus:
            if menu is None:
                continue
            children = [c for c in menu.GetChildren() if c.ControlType == auto.ControlType.MenuItemControl]
            if children:
                return children
        time.sleep(0.05)
    return []


def _expand(item) -> bool:
    found = uia.pattern(item, "ExpandCollapsePattern")
    if found is not None:
        try:
            found.Expand(waitTime=0)
            return True
        except Exception:
            pass
    found = uia.pattern(item, "InvokePattern")
    if found is not None:
        try:
            found.Invoke(waitTime=0)
            return True
        except Exception:
            pass
    return False


def _collapse_all() -> None:
    """Close any open menus (Escape closes one level at a time)."""
    for _ in range(3):
        try:
            open_menus = [c for c in auto.GetRootControl().GetChildren() if c.ControlType == auto.ControlType.MenuControl]
        except Exception:
            open_menus = []
        if not open_menus:
            return
        winapi.keys(win32con.VK_ESCAPE)
        time.sleep(0.05)


def _has_submenu(item) -> bool:
    found = uia.pattern(item, "ExpandCollapsePattern")
    try:
        return found is not None and found.ExpandCollapseState != auto.ExpandCollapseState.LeafNode
    except Exception:
        return False


def _item_info(item, path: list[str]) -> dict | None:
    title, shortcut = _split_label(uia.name_of(item))
    if not title:
        return None
    try:
        shortcut = shortcut or str(item.AcceleratorKey or "")
        enabled = bool(item.IsEnabled)
    except Exception:
        enabled = True
    return {"path": path + [title], "shortcut": shortcut, "shortcut_spoken": spoken(shortcut), "enabled": enabled}


def _uia(hwnd: int) -> list[dict]:
    window = uia.window(hwnd)
    bar = _menu_bar(window) if window is not None else None
    if bar is None:
        return []
    items: list[dict] = []
    tops = [c for c in bar.GetChildren() if c.ControlType == auto.ControlType.MenuItemControl]
    try:
        for top in tops:
            top_title = _split_label(uia.name_of(top))[0]
            if not top_title or not _expand(top):
                continue
            for item in _open_menu_items(top):
                info = _item_info(item, [top_title])
                if info is None:
                    continue
                if _has_submenu(item) and _expand(item):
                    for inner in _open_menu_items(item):
                        inner_info = _item_info(inner, info["path"])
                        if inner_info:
                            items.append(inner_info)
                    winapi.keys(win32con.VK_ESCAPE)  # (back to the first menu)
                    time.sleep(0.05)
                else:
                    items.append(info)
            _collapse_all()
    finally:
        _collapse_all()
    return items


# ---- Reading, pressing and pointing ----

def read_menus(pid: int, use_cache: bool = True, open_menus: bool = True) -> list[dict]:
    """Every menu item of the app, e.g. {"path": ["File", "Save"], "shortcut": "Ctrl+S", ...}.
    open_menus=False only reads what can be read without opening anything (for
    the phone's shortcut pad, when the user switches apps)."""
    cached = _cache.get(pid)
    if use_cache and cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    hwnd = winapi.window_of(pid)
    if not hwnd:
        return []
    items = _classic(hwnd)
    kind = "classic"
    if not items and open_menus:
        items, kind = _uia(hwnd), "uia"
    for item in items:
        _how[(pid, tuple(item["path"]))] = {"kind": kind, "hwnd": hwnd, "id": item.pop("_id", None)}
    if items:
        _cache[pid] = (time.time(), items)
    return items


def _find_uia(pid: int, path: list[str]):
    """Open the menus along `path` and return the item (menus left open)."""
    window = uia.window(winapi.window_of(pid))
    bar = _menu_bar(window) if window is not None else None
    if bar is None:
        raise LookupError(" > ".join(path))
    choices = [c for c in bar.GetChildren() if c.ControlType == auto.ControlType.MenuItemControl]
    element, opened_from = None, None
    for depth, title in enumerate(path):
        element = next((c for c in choices if _split_label(uia.name_of(c))[0] == title), None)
        if element is None:
            _collapse_all()
            raise LookupError(" > ".join(path))
        if depth < len(path) - 1:
            if not _expand(element):
                _collapse_all()
                raise LookupError(" > ".join(path))
            opened_from = element
            choices = _open_menu_items(opened_from)
    return element


def item_enabled(pid: int, path: list[str]) -> bool | None:
    how = _how.get((pid, tuple(path)))
    if not how or how["kind"] != "classic":
        return None  # (newer menus: only known by opening them; keep what the list says)
    menu = user32.GetMenu(how["hwnd"])
    for depth, title in enumerate(path):
        positions = range(max(0, user32.GetMenuItemCount(menu)))
        position = next((p for p in positions if _split_label(_menu_text(menu, p))[0] == title), None)
        if position is None:
            return None
        if depth == len(path) - 1:
            return not user32.GetMenuState(menu, position, MF_BYPOSITION) & (MF_GRAYED | MF_DISABLED)
        submenu = user32.GetSubMenu(menu, position)
        _prepare(how["hwnd"], submenu, position)
        menu = submenu
    return None


def press(pid: int, path: list[str]) -> None:
    """Click the menu item at `path`, e.g. ["File", "Save"]."""
    how = _how.get((pid, tuple(path)))
    if how and how["kind"] == "classic" and how["id"]:
        if item_enabled(pid, path) is False:
            raise MenuItemDisabled()
        win32gui.PostMessage(how["hwnd"], win32con.WM_COMMAND, how["id"], 0)
        return
    item = _find_uia(pid, path)
    try:
        if not item.IsEnabled:
            raise MenuItemDisabled()
    except MenuItemDisabled:
        _collapse_all()
        raise
    except Exception:
        pass
    if not uia.press(item):
        _collapse_all()
        raise LookupError(" > ".join(path))


def show(pid: int, path: list[str]) -> tuple[int, int, int, int] | None:
    """Open the menu so the item can be seen, and return where it is on screen.
    For items in a submenu (File > Share > Email) this is the first-level item
    ("Share"), like on the Mac."""
    try:
        item = _find_uia(pid, path[:2])
        return uia.rect(item)
    except LookupError:
        pass
    # A classic menu Windows doesn't show to UI Automation: point at its title in the menu bar.
    how = _how.get((pid, tuple(path)))
    if how and how["kind"] == "classic":
        menu = user32.GetMenu(how["hwnd"])
        positions = range(max(0, user32.GetMenuItemCount(menu)))
        position = next((p for p in positions if _split_label(_menu_text(menu, p))[0] == path[0]), None)
        box = wintypes.RECT()
        if position is not None and user32.GetMenuItemRect(how["hwnd"], menu, position, ctypes.byref(box)):
            return box.left, box.top, box.right - box.left, box.bottom - box.top
    raise LookupError(" > ".join(path))


def close(pid: int, path: list[str]) -> None:
    """Close the menu that show() opened, if it is still open."""
    try:
        _collapse_all()
    except Exception:
        pass
