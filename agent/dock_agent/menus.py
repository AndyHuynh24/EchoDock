"""Read and press menu items of the app in front, using the macOS
Accessibility API. Needs Accessibility permission (System Settings ->
Privacy & Security -> Accessibility) for the app that runs the agent
(for example Terminal)."""

import os
import time

from AppKit import NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    AXValueGetValue,
    kAXTrustedCheckOptionPrompt,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)

# Bits of AXMenuItemCmdModifiers. Command is on unless the "no command" bit is set.
SHIFT, OPTION, CONTROL, NO_COMMAND = 1, 2, 4, 8

CACHE_SECONDS = 300
_cache: dict[int, tuple[float, list[dict]]] = {}


class PermissionMissing(Exception):
    pass


class MenuItemDisabled(Exception):
    pass


def check_permission(prompt: bool = False) -> bool:
    """True if the agent may use Accessibility. With prompt=True, macOS shows
    its "allow this app" dialog."""
    if prompt:
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    return bool(AXIsProcessTrusted())


def _get(element, attribute):
    error, value = AXUIElementCopyAttributeValue(element, attribute, None)
    return value if error == 0 else None


# Keys that macOS reports as special characters or glyph codes: (symbol, spoken).
SPECIAL_KEYS = {
    "\r": ("↩", "Return"), "\x03": ("⌤", "Enter"), "\t": ("⇥", "Tab"), " ": ("Space", "Space"),
    "\x1b": ("⎋", "Escape"), "\x08": ("⌫", "Delete"), "\x7f": ("⌫", "Delete"),
}
SPECIAL_GLYPHS = {
    11: ("↩", "Return"), 4: ("⌤", "Enter"), 2: ("⇥", "Tab"), 9: ("Space", "Space"),
    27: ("⎋", "Escape"), 23: ("⌫", "Delete"), 10: ("⌦", "Forward Delete"),
    100: ("←", "Left Arrow"), 101: ("→", "Right Arrow"), 104: ("↑", "Up Arrow"), 106: ("↓", "Down Arrow"),
}


def _shortcut(item) -> tuple[str, str]:
    """Return the shortcut as symbols ("⇧⌘B") and as words ("Shift Command B")."""
    key = _get(item, "AXMenuItemCmdChar")
    glyph = _get(item, "AXMenuItemCmdGlyph")
    if glyph in SPECIAL_GLYPHS:
        key, key_spoken = SPECIAL_GLYPHS[glyph]
    elif isinstance(glyph, int) and 111 <= glyph <= 122:  # F1 to F12
        key = key_spoken = f"F{glyph - 110}"
    elif key and 0xF704 <= ord(key[0]) <= 0xF70F:  # F1 to F12 sent as a private character
        key = key_spoken = f"F{ord(key[0]) - 0xF703}"
    elif key in SPECIAL_KEYS:
        key, key_spoken = SPECIAL_KEYS[key]
    elif key:
        key_spoken = key
    else:
        return "", ""
    mods = _get(item, "AXMenuItemCmdModifiers") or 0
    symbols, words = "", []
    if mods & CONTROL:
        symbols += "⌃"
        words.append("Control")
    if mods & OPTION:
        symbols += "⌥"
        words.append("Option")
    if mods & SHIFT:
        symbols += "⇧"
        words.append("Shift")
    if not mods & NO_COMMAND:
        symbols += "⌘"
        words.append("Command")
    return symbols + key, " ".join(words + [key_spoken])


def _walk(menu, path: list[str], items: list[dict]) -> None:
    for item in _get(menu, "AXChildren") or []:
        title = _get(item, "AXTitle")
        if not title:
            continue  # separators have no title
        item_path = path + [title]
        submenus = _get(item, "AXChildren") or []
        if submenus:
            for submenu in submenus:
                _walk(submenu, item_path, items)
            continue
        shortcut, spoken = _shortcut(item)
        items.append({
            "path": item_path,
            "shortcut": shortcut,
            "shortcut_spoken": spoken,
            "enabled": bool(_get(item, "AXEnabled")),
        })


def front_window(pid: int) -> tuple[str, str]:
    """Title and document path of the app's focused window ("" if unknown)."""
    from urllib.parse import unquote, urlparse
    app = AXUIElementCreateApplication(pid)
    window = _get(app, "AXFocusedWindow") or _get(app, "AXMainWindow")
    if window is None:
        return "", ""
    document = _get(window, "AXDocument")
    return str(_get(window, "AXTitle") or ""), unquote(urlparse(str(document)).path) if document else ""


_last_other_app = None  # the last app in front that wasn't Dock itself


def front_app() -> tuple[str, int]:
    """The app the user is working in. If Dock's own window is in front (its
    chat box or settings), that's the app they were using just before."""
    global _last_other_app
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if int(app.processIdentifier()) == os.getpid() and _last_other_app is not None:
        app = _last_other_app
    elif int(app.processIdentifier()) != os.getpid():
        _last_other_app = app
    return str(app.localizedName()), int(app.processIdentifier())


def read_menus(pid: int, use_cache: bool = True) -> list[dict]:
    """Every menu item of the app, e.g. {"path": ["Modify", "Split Clip"], "shortcut": "⌘B", ...}."""
    if not check_permission():
        raise PermissionMissing()
    cached = _cache.get(pid)
    if use_cache and cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    menu_bar = _get(AXUIElementCreateApplication(pid), "AXMenuBar")
    items: list[dict] = []
    for top in (_get(menu_bar, "AXChildren") or [])[1:]:  # [0] is the Apple menu
        title = _get(top, "AXTitle")
        for menu in _get(top, "AXChildren") or []:
            _walk(menu, [title], items)
    if items:  # an app that is still launching has no menus yet; don't remember that
        _cache[pid] = (time.time(), items)
    return items


def _elements(pid: int, path: list[str]) -> list:
    """The menu elements along `path`, e.g. ["Modify", "Split Clip"] gives
    [the Modify menu bar item, the Split Clip item]."""
    element = _get(AXUIElementCreateApplication(pid), "AXMenuBar")
    found = []
    for depth, title in enumerate(path):
        children = _get(element, "AXChildren") or []
        if depth > 0:
            # Below the top level, each item's children are wrapped in a menu.
            children = [c for menu in children for c in (_get(menu, "AXChildren") or [])]
        element = next((c for c in children if _get(c, "AXTitle") == title), None)
        if element is None:
            raise LookupError(" > ".join(path))
        found.append(element)
    return found


def _rect(element) -> tuple[float, float, float, float] | None:
    """Where the element is on screen: (x, y, width, height), measured from the
    top-left of the main screen. None if it isn't showing."""
    position, size = _get(element, "AXPosition"), _get(element, "AXSize")
    if position is None or size is None:
        return None
    point = AXValueGetValue(position, kAXValueCGPointType, None)[1]
    extent = AXValueGetValue(size, kAXValueCGSizeType, None)[1]
    return (point.x, point.y, extent.width, extent.height) if extent.width > 0 else None


def press(pid: int, path: list[str]) -> None:
    """Click the menu item at `path`, e.g. ["Modify", "Split Clip"]."""
    if not check_permission():
        raise PermissionMissing()
    item = _elements(pid, path)[-1]
    if not _get(item, "AXEnabled"):
        raise MenuItemDisabled()
    AXUIElementPerformAction(item, "AXPress")


def show(pid: int, path: list[str]) -> tuple[float, float, float, float] | None:
    """Open the menu so the item can be seen, and return where it is on screen.
    For items in a submenu (File > Share > File...) this returns the first-level
    item ("Share"), since submenus only open when hovered."""
    if not check_permission():
        raise PermissionMissing()
    elements = _elements(pid, path)
    if len(elements) > 1:
        AXUIElementPerformAction(elements[0], "AXPress")
        for _ in range(20):  # the menu takes a moment to appear
            time.sleep(0.03)
            rect = _rect(elements[1])
            if rect:
                return rect
    return _rect(elements[0])


def close(pid: int, path: list[str]) -> None:
    """Close the menu that show() opened, if it is still open."""
    try:
        top = _elements(pid, path[:1])[0]
    except LookupError:
        return
    for menu in _get(top, "AXChildren") or []:
        AXUIElementPerformAction(menu, "AXCancel")
