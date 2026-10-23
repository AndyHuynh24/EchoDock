"""Read and press menu items of the front app on Windows.

Classic Win32 menus are read directly (WM_COMMAND to press). Newer menus are only
visible to UI Automation while open, so they're opened briefly when needed. Apps
without a menu bar are handled by onscreen.py.
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
MENU_TIMEOUT = 1.0
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
_how: dict[tuple[int, tuple], dict] = {}  # (pid, path) -> {"kind": "classic", "hwnd", "id"} or {"kind": "uia"}
_last_other = None


class PermissionMissing(Exception):
    """Never raised: UI Automation needs no permission."""


class MenuItemDisabled(Exception):
    pass


def check_permission(prompt: bool = False) -> bool:
    return True


# ---- shortcuts ----

SPOKEN_KEYS = {"ctrl": "Control", "alt": "Alt", "shift": "Shift", "win": "Windows", "del": "Delete",
               "ins": "Insert", "esc": "Escape", "pgup": "Page Up", "pgdn": "Page Down", "bksp": "Backspace",
               "enter": "Enter", "tab": "Tab", "space": "Space", "plus": "Plus", "minus": "Minus",
               "up": "Up Arrow", "down": "Down Arrow", "left": "Left Arrow", "right": "Right Arrow"}


def spoken(shortcut: str) -> str:
    if not shortcut:
        return ""
    parts = [p for p in re.split(r"\+(?=.)", shortcut.strip()) if p]
    return " ".join(SPOKEN_KEYS.get(p.strip().lower(), p.strip()) for p in parts)


def _split_label(text: str) -> tuple[str, str]:
    title, _, shortcut = text.partition("\t")
    title = re.sub(r"&(.)", r"\1", title).strip()
    return title, shortcut.strip()


# ---- front app ----

def front_app() -> tuple[str, int]:
    """The user's app (the previous one if Dock itself is in front)."""
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
    """Title and file of the app's window, if known."""
    hwnd = winapi.window_of(pid)
    window_title = winapi.title(hwnd) if hwnd else ""
    return window_title, winapi.document_in_title(window_title) if window_title else ""


# ---- classic menus ----

def _menu_text(menu, position: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetMenuStringW(menu, position, buffer, len(buffer), MF_BYPOSITION)
    return buffer.value


def _prepare(hwnd: int, menu, position: int) -> None:
    """Send WM_INITMENUPOPUP so the app updates its items."""
    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(hwnd, WM_INITMENUPOPUP, menu, position, 0x2, 200, ctypes.byref(result))


def _walk_classic(hwnd: int, menu, path: list[str], items: list[dict], depth: int = 0) -> None:
    for position in range(max(0, user32.GetMenuItemCount(menu))):
        state = user32.GetMenuState(menu, position, MF_BYPOSITION)
        if state == NO_ID or state & MF_SEPARATOR:
            continue
        title, shortcut = _split_label(_menu_text(menu, position))
        if not title:
            continue  # owner-drawn, no text
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


# ---- UI Automation menus ----

def _menu_bar(window):
    """The app's menu bar (not the system menu)."""
    for found in uia.find_all(window, max_seconds=1.0):
        if found.type == auto.ControlType.MenuBarControl and found.name.lower() not in SKIP_MENUS:
            control = found.control()
            parent = control.GetParentControl() if control is not None else None
            if parent is not None and parent.ControlType == auto.ControlType.TitleBarControl:
                continue
            return control
    return None


def _open_menu_items(opened_from=None) -> list:
    """Items of the menu that just opened (top-level popup, under the item, or inside the window)."""
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
    """Close open menus."""
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
                    winapi.keys(win32con.VK_ESCAPE)
                    time.sleep(0.05)
                else:
                    items.append(info)
            _collapse_all()
    finally:
        _collapse_all()
    return items


# ---- read, press, point ----

def read_menus(pid: int, use_cache: bool = True, open_menus: bool = True) -> list[dict]:
    """All menu items. open_menus=False reads only what's available without opening menus."""
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
        return None
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
    """Click the menu item at `path`."""
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
    """Open the menu and return the item's frame (first-level item for submenus)."""
    try:
        item = _find_uia(pid, path[:2])
        return uia.rect(item)
    except LookupError:
        pass
    # Classic menus hidden from UI Automation: point at the menu bar title.
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
    """Close the menu opened by show()."""
    try:
        _collapse_all()
    except Exception:
        pass
