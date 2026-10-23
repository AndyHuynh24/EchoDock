"""Help for controls outside the menus on Windows: named controls via UI Automation,
then a window screenshot for the server's vision model.
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
MIN_SHOWING = 0.6  # visible fraction required
SHOT_WIDTH = 1280  # screenshot width sent to the model

_controls: list = []


class NotAllowed(Exception):
    pass


def screen_permission(ask: bool = False) -> bool:
    return True


def _showing(rect, clip) -> bool:
    if rect[2] < 4 or rect[3] < 4:
        return False
    left, top = max(rect[0], clip[0]), max(rect[1], clip[1])
    right, bottom = min(rect[0] + rect[2], clip[0] + clip[2]), min(rect[1] + rect[3], clip[1] + clip[3])
    return right > left and bottom > top and (right - left) * (bottom - top) >= MIN_SHOWING * rect[2] * rect[3]


def window_controls() -> dict:
    """Visible named controls in the front window."""
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
                name = f"{name} ({part.accelerator})"
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
    """Screenshot of the front window (shrunk) and its frame on screen."""
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
    """High-resolution capture of a screen region."""
    sx, sy, sw, sh = winapi.screen_of((rect[0] + rect[2] / 2, rect[1] + rect[3] / 2))["full"]
    width, height = min(rect[2], sw), min(rect[3], sh)
    x = min(max(rect[0], sx), sx + sw - width)
    y = min(max(rect[1], sy), sy + sh - height)
    x, y, width, height = (int(round(v)) for v in (x, y, width, height))
    image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
    return {"image": _png(image), "width": image.width, "height": image.height, "bounds": [x, y, width, height]}


def click(x: float, y: float) -> None:
    """Left click at (x, y) in screen pixels."""
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
