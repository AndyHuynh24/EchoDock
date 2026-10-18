"""Help with things that aren't in an app's menus, on Windows: toolbar
buttons, ribbon buttons, icons and other controls in the window (the same
answers as dock_agent/onscreen.py on the Mac).

1. The window's own controls (free, exact): UI Automation lists buttons with
   their names (Chrome's "Downloads", Word's ribbon buttons, VS Code's
   "Toggle Panel (Ctrl+J)"). Dock points at the real button, and "do it"
   presses it.
2. A screenshot of only the window in front, taken when the user asks and
   nothing else found it. The server asks the AI where the control is; Dock
   circles that spot, and "do it" clicks there. (Windows asks no permission for this.)
"""

import base64
import io
import time

import uiautomation as auto
import win32api
import win32con
from PIL import ImageGrab

from dock_agent.win import menus, uia, winapi

ControlType = auto.ControlType
CONTROL_TYPES = {ControlType.ButtonControl, ControlType.CheckBoxControl, ControlType.RadioButtonControl,
                 ControlType.SplitButtonControl, ControlType.HyperlinkControl, ControlType.ComboBoxControl,
                 ControlType.TabItemControl, ControlType.MenuItemControl, ControlType.EditControl}
ROLE_NAMES = {ControlType.ButtonControl: "button", ControlType.CheckBoxControl: "checkbox",
              ControlType.RadioButtonControl: "radio button", ControlType.SplitButtonControl: "button",
              ControlType.HyperlinkControl: "link", ControlType.ComboBoxControl: "pop-up button",
              ControlType.TabItemControl: "tab", ControlType.MenuItemControl: "menu button",
              ControlType.EditControl: "text field"}
MAX_CONTROLS = 400
MIN_SHOWING = 0.6       # this much of a control must be inside the window
SHOT_WIDTH = 1280       # the screenshot is shrunk to this width for the AI

_controls: list = []    # the elements from the last look, by number


class NotAllowed(Exception):
    pass


def screen_permission(ask: bool = False) -> bool:
    return True  # (Windows lets apps take screenshots without asking)


def _showing(rect, clip) -> bool:
    if rect[2] < 4 or rect[3] < 4:
        return False
    left, top = max(rect[0], clip[0]), max(rect[1], clip[1])
    right, bottom = min(rect[0] + rect[2], clip[0] + clip[2]), min(rect[1] + rect[3], clip[1] + clip[3])
    return right > left and bottom > top and (right - left) * (bottom - top) >= MIN_SHOWING * rect[2] * rect[3]


def window_controls() -> dict:
    """The named buttons and other controls in the front app's window that are showing."""
    global _controls
    app_name, pid = menus.front_app()
    hwnd = winapi.window_of(pid)
    window = uia.window(hwnd)
    clip = winapi.rect(hwnd)
    found = []
    if window is not None and clip is not None:
        for part in uia.find_all(window):
            if len(found) >= MAX_CONTROLS:
                break
            if part.type not in CONTROL_TYPES or not part.name or part.offscreen or part.rect is None:
                continue
            if part.password or not _showing(part.rect, clip):
                continue
            name = part.name[:80]
            if part.accelerator and part.accelerator not in name:
                name = f"{name} ({part.accelerator})"  # (the server reads shortcuts in names, like VS Code's)
            found.append((part.element, {"name": name, "role": ROLE_NAMES.get(part.type, "button"), "where": "window",
                                         "enabled": part.enabled, "rect": part.rect}))
    _controls = [element for element, _ in found]
    title, _ = menus.front_window(pid)
    return {"app": app_name, "pid": pid, "window": title,
            "controls": [dict(info, number=n) for n, (_, info) in enumerate(found)]}


def _control(number: int):
    if not 0 <= number < len(_controls):
        raise LookupError("That button is gone.")
    control = auto.Control.CreateControlFromElement(_controls[number])
    if control is None:
        raise LookupError("That button is gone.")
    return control


def control_rect(number: int):
    rect = uia.rect(_control(number))
    if rect is None:
        raise LookupError("That button isn't showing anymore.")
    return rect


def press_control(number: int) -> None:
    control = _control(number)
    rect = uia.rect(control)
    if rect is None:
        raise LookupError("That button isn't showing anymore.")
    if not uia.press(control):
        click(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)


def _png(image) -> str:
    data = io.BytesIO()
    image.save(data, "PNG")
    return base64.b64encode(data.getvalue()).decode()


def window_screenshot() -> dict:
    """A screenshot of only the front app's window, shrunk for the AI, and
    where that window is on screen (pixels, from the top-left)."""
    app_name, pid = menus.front_app()
    hwnd = winapi.window_of(pid)
    bounds = winapi.rect(hwnd) if hwnd else None
    if bounds is None:
        raise LookupError(f"I can't see a {app_name} window.")
    x, y, w, h = bounds
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    if image.width > SHOT_WIDTH:
        image = image.resize((SHOT_WIDTH, round(image.height * SHOT_WIDTH / image.width)))
    return {"app": app_name, "pid": pid, "image": _png(image), "width": image.width, "height": image.height,
            "bounds": [x, y, w, h]}


def screen_region(rect: list[float]) -> dict:
    """A sharp close-up of part of the screen, kept on the screen the spot is on."""
    sx, sy, sw, sh = winapi.screen_of((rect[0] + rect[2] / 2, rect[1] + rect[3] / 2))["full"]
    width, height = min(rect[2], sw), min(rect[3], sh)
    x = min(max(rect[0], sx), sx + sw - width)
    y = min(max(rect[1], sy), sy + sh - height)
    x, y, width, height = (int(round(v)) for v in (x, y, width, height))
    image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
    return {"image": _png(image), "width": image.width, "height": image.height, "bounds": [x, y, width, height]}


def click(x: float, y: float) -> None:
    """One left click at (x, y), in screen pixels from the top-left."""
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
