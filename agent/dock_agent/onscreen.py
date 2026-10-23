"""Help for controls outside the menus: named window controls via Accessibility,
then a window screenshot for the server's vision model (needs Screen Recording).
"""

import base64
import os
import subprocess
import tempfile
import time

from ApplicationServices import AXUIElementCreateApplication, AXUIElementPerformAction, AXUIElementSetAttributeValue
from Quartz import (
    CGEventCreateMouseEvent,
    CGEventPost,
    CGPreflightScreenCaptureAccess,
    CGRequestScreenCaptureAccess,
    CGWindowListCopyWindowInfo,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventMouseMoved,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
    kCGNullWindowID,
    kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly,
)

from dock_agent import menus

CONTROL_ROLES = {"AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton",
                 "AXDisclosureTriangle", "AXLink", "AXSlider", "AXComboBox", "AXTextField", "AXSearchField"}
MAX_CONTROLS = 400
MAX_VISITED = 4000
MAX_SECONDS = 2.0
MIN_SHOWING = 0.6  # visible fraction required
CLIPPING_ROLES = {"AXScrollArea", "AXWebArea"}
SHOT_WIDTH = 1280  # screenshot width sent to the model

_controls: list = []


class NotAllowed(Exception):
    pass


def screen_permission(ask: bool = False) -> bool:
    """Whether screenshots are allowed. ask=True prompts once."""
    return bool(CGRequestScreenCaptureAccess() if ask else CGPreflightScreenCaptureAccess())


def _name(element) -> str:
    for attribute in ("AXTitle", "AXDescription", "AXHelp", "AXPlaceholderValue"):
        value = menus._get(element, attribute)
        if value and str(value).strip():
            return " ".join(str(value).split())[:80]
    return ""


def _overlap(rect, clip) -> tuple | None:
    """Intersection of rect and clip, or None."""
    left, top = max(rect[0], clip[0]), max(rect[1], clip[1])
    right, bottom = min(rect[0] + rect[2], clip[0] + clip[2]), min(rect[1] + rect[3], clip[1] + clip[3])
    return (left, top, right - left, bottom - top) if right > left and bottom > top else None


def _showing(rect, clip) -> bool:
    """Whether most of the control is actually visible (web apps list hidden elements too)."""
    if rect[2] < 4 or rect[3] < 4:
        return False
    part = _overlap(rect, clip) if clip else rect
    return part is not None and part[2] * part[3] >= MIN_SHOWING * rect[2] * rect[3]


def window_controls() -> dict:
    """Visible named controls in the front window."""
    global _controls
    app_name, pid = menus.front_app()
    app = AXUIElementCreateApplication(pid)
    # Chromium-based apps expose their tree only on request.
    AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    window = menus._get(app, "AXFocusedWindow") or menus._get(app, "AXMainWindow")
    found, seen = [], 0
    start = time.time()
    stack = [(window, "", menus._rect(window) if window is not None else None)] if window is not None else []
    while stack and len(found) < MAX_CONTROLS and seen < MAX_VISITED and time.time() - start < MAX_SECONDS:
        element, where, clip = stack.pop()
        seen += 1
        role = str(menus._get(element, "AXRole") or "")
        if role == "AXToolbar":
            where = "toolbar"
        if role in CLIPPING_ROLES:
            rect = menus._rect(element)
            clip = (_overlap(rect, clip) if clip else rect) if rect else clip
            if clip is None:
                continue
        if role in CONTROL_ROLES:
            name = _name(element)
            rect = menus._rect(element)
            if name and rect and _showing(rect, clip):
                found.append((element, {"name": name, "role": str(menus._get(element, "AXRoleDescription") or role),
                                        "where": where or "window", "enabled": menus._get(element, "AXEnabled") is not False,
                                        "rect": rect}))
        children = menus._get(element, "AXChildren") or []
        stack.extend((child, where, clip) for child in reversed(list(children)))
    _controls = [element for element, _ in found]
    title, _ = menus.front_window(pid)
    return {"app": app_name, "pid": pid, "window": title,
            "controls": [dict(info, number=n) for n, (_, info) in enumerate(found)]}


def control_rect(number: int):
    if not 0 <= number < len(_controls):
        raise LookupError("That button is gone.")
    rect = menus._rect(_controls[number])
    if rect is None:
        raise LookupError("That button isn't showing anymore.")
    return rect


def press_control(number: int) -> None:
    control_rect(number)
    AXUIElementPerformAction(_controls[number], "AXPress")


def window_screenshot() -> dict:
    """Screenshot of the front window (shrunk) and its frame on screen."""
    if not screen_permission():
        screen_permission(ask=True)
        raise NotAllowed("To look at your screen, Dock needs Screen Recording. Open Dock from the menu bar to allow it.")
    app_name, pid = menus.front_app()
    windows = [w for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID)
               if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0]
    if not windows:
        raise LookupError(f"I can't see a {app_name} window.")
    window = windows[0]
    bounds = window["kCGWindowBounds"]
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "window.png")
        subprocess.run(["screencapture", "-x", "-o", f"-l{window['kCGWindowNumber']}", path], check=True, timeout=10)
        subprocess.run(["sips", "--resampleWidth", str(SHOT_WIDTH), path], capture_output=True, check=True)
        size = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path], capture_output=True, text=True).stdout.split()
        width, height = int(size[size.index("pixelWidth:") + 1]), int(size[size.index("pixelHeight:") + 1])
        with open(path, "rb") as f:
            image = base64.b64encode(f.read()).decode()
    return {"app": app_name, "pid": pid, "image": image, "width": width, "height": height,
            "bounds": [bounds["X"], bounds["Y"], bounds["Width"], bounds["Height"]]}


def screen_region(rect: list[float]) -> dict:
    """High-resolution capture of a screen region, for small controls."""
    if not screen_permission():
        raise NotAllowed("To look at your screen, Dock needs Screen Recording.")
    # Clamp to the screen containing the spot.
    from AppKit import NSScreen
    main_height = NSScreen.screens()[0].frame().size.height
    cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
    for screen in NSScreen.screens():
        f = screen.frame()
        left, top = f.origin.x, main_height - f.origin.y - f.size.height
        if left <= cx < left + f.size.width and top <= cy < top + f.size.height:
            break
    width, height = min(rect[2], f.size.width), min(rect[3], f.size.height)
    x = min(max(rect[0], left), left + f.size.width - width)
    y = min(max(rect[1], top), top + f.size.height - height)
    x, y, width, height = (int(round(v)) for v in (x, y, width, height))
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "zoom.png")
        subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{width},{height}", path], check=True, timeout=10)
        size = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path], capture_output=True, text=True).stdout.split()
        pixels = int(size[size.index("pixelWidth:") + 1]), int(size[size.index("pixelHeight:") + 1])
        with open(path, "rb") as f:
            image = base64.b64encode(f.read()).decode()
    return {"image": image, "width": pixels[0], "height": pixels[1], "bounds": [x, y, width, height]}


def click(x: float, y: float) -> None:
    """Left click at (x, y) in screen points."""
    for kind in (kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp):
        CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kind, (x, y), kCGMouseButtonLeft))
        time.sleep(0.05)
