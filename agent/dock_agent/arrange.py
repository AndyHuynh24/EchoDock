"""Arrange windows by voice: "Chrome on the left and my notes on the right",
"make this full screen", "move this to my other screen", "hide everything
but this".

Moves and sizes each app's front window with Accessibility. Places are parts
of the screen's usable area (below the menu bar and beside the macOS Dock).
An app that isn't open yet is opened first.

Windows: SetWindowPos with the monitor's work area (docs/WINDOWS-PORT.md).
"""

import os
import time

from AppKit import NSBundle, NSRunningApplication, NSScreen, NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from Quartz import CGPoint, CGSize

from dock_agent import apps, menus

# (left, top, width, height) as parts of the screen.
PLACES = {
    "left": (0, 0, 1 / 2, 1), "right": (1 / 2, 0, 1 / 2, 1),
    "top": (0, 0, 1, 1 / 2), "bottom": (0, 1 / 2, 1, 1 / 2),
    "full": (0, 0, 1, 1), "center": (0.15, 0.08, 0.7, 0.84),
    "left third": (0, 0, 1 / 3, 1), "middle third": (1 / 3, 0, 1 / 3, 1), "right third": (2 / 3, 0, 1 / 3, 1),
    "left two thirds": (0, 0, 2 / 3, 1), "right two thirds": (1 / 3, 0, 2 / 3, 1),
    "top left": (0, 0, 1 / 2, 1 / 2), "top right": (1 / 2, 0, 1 / 2, 1 / 2),
    "bottom left": (0, 1 / 2, 1 / 2, 1 / 2), "bottom right": (1 / 2, 1 / 2, 1 / 2, 1 / 2),
}
GAP = 4  # points between windows, so their edges don't overlap
KEEP = "as is"  # leave the window where it is (just bring it forward): "hide everything except VS Code"


class ArrangeError(Exception):
    pass


def _running(name: str):
    """The running app for a spoken name ("" or "this" = the app in front), opening it if needed."""
    workspace = NSWorkspace.sharedWorkspace()
    if name.strip().lower() in ("", "this", "this app", "this window", "it"):
        return workspace.frontmostApplication()
    found = apps.find_app(name)
    # Only a close match ("chrome" for Google Chrome), never a guess ("Photoshop" must not open Photos).
    target = apps._norm(name)
    if found is None or not (apps._norm(found[0]).startswith(target) or target in apps.ALIASES
                             or any(apps._norm(word).startswith(target) for word in found[0].split())):
        raise ArrangeError(f"I couldn't find an app called {name}.")
    app_name, path = found
    bundle_id = NSBundle.bundleWithPath_(str(path)).bundleIdentifier()

    def running():  # (asked fresh each time: the workspace's own list can lag behind)
        found = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) if bundle_id else []
        return found[0] if found else None

    if running() is None:
        apps.open_app(app_name)
        for _ in range(80):  # wait up to 8 s for it to start
            time.sleep(0.1)
            if running() is not None:
                break
    if running() is None:
        raise ArrangeError(f"{app_name} didn't open.")
    return running()


def _window(app):
    """The app's front window (waiting a moment for a just-opened app)."""
    element = AXUIElementCreateApplication(app.processIdentifier())
    for _ in range(30):
        window = menus._get(element, "AXFocusedWindow") or menus._get(element, "AXMainWindow")
        if window is None:
            windows = [w for w in menus._get(element, "AXWindows") or [] if not menus._get(w, "AXMinimized")]
            window = windows[0] if windows else None
        if window is not None:
            return window
        time.sleep(0.1)
    raise ArrangeError(f"{app.localizedName()} has no window open.")


def _screens() -> list[tuple[float, float, float, float]]:
    """Each screen's usable area as (x, y, width, height) from the top-left of the main screen."""
    main_height = NSScreen.screens()[0].frame().size.height
    areas = []
    for screen in NSScreen.screens():
        f = screen.visibleFrame()
        areas.append((f.origin.x, main_height - f.origin.y - f.size.height, f.size.width, f.size.height))
    return areas


def _screen_of(rect) -> int:
    if rect is None:
        return 0
    cx, cy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
    for n, (x, y, w, h) in enumerate(_screens()):
        if x <= cx < x + w and y <= cy < y + h:
            return n
    return 0


def _move(window, rect) -> None:
    x, y, w, h = rect
    position = AXValueCreate(kAXValueCGPointType, CGPoint(x, y))
    AXUIElementSetAttributeValue(window, "AXPosition", position)
    AXUIElementSetAttributeValue(window, "AXSize", AXValueCreate(kAXValueCGSizeType, CGSize(w, h)))
    AXUIElementSetAttributeValue(window, "AXPosition", position)  # (some apps move it back after a resize)


def arrange(layout: list[dict], screen: str = "this", hide_others: bool = False) -> dict:
    """layout: [{"app": "Chrome", "place": "left"}, ...]; app "" means the app in front.
    screen: "this" (where the first window is), "other" (the next screen) or "main"."""
    if not menus.check_permission():
        raise ArrangeError("Dock needs the Accessibility permission to move windows.")
    screens = _screens()
    done, problems, keep = [], [], set()
    target = None
    for item in layout:
        place = str(item.get("place", "")).strip().lower()
        if place not in PLACES and place != KEEP:
            problems.append(f"I don't know the place {place}.")
            continue
        try:
            app = _running(str(item.get("app", "")))
            window = _window(app)
        except ArrangeError as e:
            problems.append(str(e))
            continue
        keep.add(app.processIdentifier())
        if place == KEEP:
            app.activateWithOptions_(0)
            done.append({"app": str(app.localizedName()), "place": place})
            continue
        if menus._get(window, "AXFullScreen"):
            AXUIElementSetAttributeValue(window, "AXFullScreen", False)
            time.sleep(1.0)  # leaving full screen animates
        if target is None:
            here = _screen_of(menus._rect(window))
            target = {"other": (here + 1) % len(screens), "main": 0}.get(screen, here)
        sx, sy, sw, sh = screens[target]
        left, top, width, height = PLACES[place]
        rect = (sx + left * sw + GAP, sy + top * sh + GAP, width * sw - 2 * GAP, height * sh - 2 * GAP)
        _move(window, rect)
        app.activateWithOptions_(0)
        done.append({"app": str(app.localizedName()), "place": place})
    if hide_others and done:
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if (app.activationPolicy() == 0 and app.processIdentifier() not in keep
                    and app.processIdentifier() != os.getpid() and not app.isHidden()):
                app.hide()
    return {"arranged": done, "problems": problems, "screens": len(screens)}
