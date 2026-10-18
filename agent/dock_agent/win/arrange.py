"""Arrange windows by voice on Windows: "Chrome on the left and my notes on
the right", "make this full screen", "move this to my other screen", "hide
everything but this" (the same answers as dock_agent/arrange.py on the Mac).

Places are parts of the screen's usable area (without the taskbar); "full"
maximizes the window. An app that isn't open yet is opened first.
"""

import time

import win32con
import win32gui

from dock_agent.win import apps, winapi

PLACES = {
    "left": (0, 0, 1 / 2, 1), "right": (1 / 2, 0, 1 / 2, 1),
    "top": (0, 0, 1, 1 / 2), "bottom": (0, 1 / 2, 1, 1 / 2),
    "full": (0, 0, 1, 1), "center": (0.15, 0.08, 0.7, 0.84),
    "left third": (0, 0, 1 / 3, 1), "middle third": (1 / 3, 0, 1 / 3, 1), "right third": (2 / 3, 0, 1 / 3, 1),
    "left two thirds": (0, 0, 2 / 3, 1), "right two thirds": (1 / 3, 0, 2 / 3, 1),
    "top left": (0, 0, 1 / 2, 1 / 2), "top right": (1 / 2, 0, 1 / 2, 1 / 2),
    "bottom left": (0, 1 / 2, 1 / 2, 1 / 2), "bottom right": (1 / 2, 1 / 2, 1 / 2, 1 / 2),
}
GAP = 4  # pixels between windows
KEEP = "as is"  # leave the window where it is (just bring it forward): "hide everything except VS Code"


class ArrangeError(Exception):
    pass


def _window(name: str) -> int:
    """The window for a spoken app name ("" or "this" = the window in front), opening the app if needed."""
    if name.strip().lower() in ("", "this", "this app", "this window", "it"):
        from dock_agent.win import menus
        _, pid = menus.front_app()
        hwnd = winapi.window_of(pid)
        if not hwnd:
            raise ArrangeError("I don't see a window in front.")
        return hwnd
    hwnd = apps.running_window(name)
    if hwnd:
        return hwnd
    found = apps.find_app(name)
    target = apps._norm(name)
    # Only a close match ("chrome" for Google Chrome), never a guess.
    if found is None or not (apps._norm(found[0]).startswith(target) or target in apps.ALIASES
                             or any(apps._norm(word).startswith(target) for word in found[0].split())):
        raise ArrangeError(f"I couldn't find an app called {name}.")
    apps.launch(found[1])
    for _ in range(80):  # wait up to 8 s for its window
        time.sleep(0.1)
        hwnd = apps.running_window(found[0])
        if hwnd:
            time.sleep(0.3)
            return hwnd
    raise ArrangeError(f"{found[0]} didn't open.")


def _screen_index(hwnd: int, screens: list[dict]) -> int:
    box = winapi.rect(hwnd)
    if box is None:
        return 0
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    for n, screen in enumerate(screens):
        x, y, w, h = screen["full"]
        if x <= cx < x + w and y <= cy < y + h:
            return n
    return 0


def _move(hwnd: int, rect, maximize: bool) -> None:
    if win32gui.IsIconic(hwnd) or (win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWMAXIMIZED):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.15)
    x, y, w, h = rect
    left, top, right, bottom = winapi.borders(hwnd)  # (so the visible edges line up, not the invisible ones)
    win32gui.SetWindowPos(hwnd, 0, int(x - left), int(y - top), int(w + left + right), int(h + top + bottom),
                          win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
    if maximize:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)


def arrange(layout: list[dict], screen: str = "this", hide_others: bool = False) -> dict:
    """layout: [{"app": "Chrome", "place": "left"}, ...]; app "" means the app in front.
    screen: "this" (where the first window is), "other" (the next screen) or "main"."""
    screens = winapi.screens()
    done, problems, keep = [], [], set()
    target = None
    for item in layout:
        place = str(item.get("place", "")).strip().lower()
        if place not in PLACES and place != KEEP:
            problems.append(f"I don't know the place {place}.")
            continue
        try:
            hwnd = _window(str(item.get("app", "")))
        except ArrangeError as e:
            problems.append(str(e))
            continue
        keep.add(hwnd)
        if place == KEEP:
            winapi.bring_forward(hwnd)
            done.append({"app": winapi.app_name(winapi.window_pid(hwnd), hwnd), "place": place})
            continue
        if target is None:
            here = _screen_index(hwnd, screens)
            target = {"other": (here + 1) % len(screens), "main": 0}.get(screen, here)
        sx, sy, sw, sh = screens[target]["area"]
        left, top, width, height = PLACES[place]
        rect = (sx + left * sw + GAP, sy + top * sh + GAP, width * sw - 2 * GAP, height * sh - 2 * GAP)
        _move(hwnd, rect, maximize=place == "full")
        winapi.bring_forward(hwnd)
        done.append({"app": winapi.app_name(winapi.window_pid(hwnd), hwnd), "place": place})
    if hide_others and done:
        for hwnd in winapi.app_windows():
            if hwnd not in keep:
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    return {"arranged": done, "problems": problems, "screens": len(screens)}
