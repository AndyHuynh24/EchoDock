"""Arrange windows by voice ("Chrome on the left, notes on the right", "full screen").

Uses Accessibility to move and size each app's front window within the usable screen area.
"""

import os
import time

from AppKit import NSBundle, NSRunningApplication, NSScreen, NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from Quartz import CGPoint, CGSize

from dock_agent import apps, menus

# (left, top, width, height) as fractions of the screen.
PLACES = {
    "left": (0, 0, 1 / 2, 1), "right": (1 / 2, 0, 1 / 2, 1),
    "top": (0, 0, 1, 1 / 2), "bottom": (0, 1 / 2, 1, 1 / 2),
    "full": (0, 0, 1, 1), "center": (0.15, 0.08, 0.7, 0.84),
    "left third": (0, 0, 1 / 3, 1), "middle third": (1 / 3, 0, 1 / 3, 1), "right third": (2 / 3, 0, 1 / 3, 1),
    "left two thirds": (0, 0, 2 / 3, 1), "right two thirds": (1 / 3, 0, 2 / 3, 1),
    "top left": (0, 0, 1 / 2, 1 / 2), "top right": (1 / 2, 0, 1 / 2, 1 / 2),
    "bottom left": (0, 1 / 2, 1 / 2, 1 / 2), "bottom right": (1 / 2, 1 / 2, 1 / 2, 1 / 2),
}
GAP = 4  # gap between windows
KEEP = "as is"  # bring forward without moving


class ArrangeError(Exception):
    pass


def _running(name: str):
    """Running app for a spoken name ("" or "this" = front app), opening it if needed."""
    workspace = NSWorkspace.sharedWorkspace()
    if name.strip().lower() in ("", "this", "this app", "this window", "it"):
        return workspace.frontmostApplication()
    found = apps.find_app(name)
    # Close matches only, never a guess.
    target = apps._norm(name)
    if found is None or not (apps._norm(found[0]).startswith(target) or target in apps.ALIASES
                             or any(apps._norm(word).startswith(target) for word in found[0].split())):
        raise ArrangeError(f"I couldn't find an app called {name}.")
    app_name, path = found
    bundle_id = NSBundle.bundleWithPath_(str(path)).bundleIdentifier()

    def running():
        found = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) if bundle_id else []
        return found[0] if found else None

    if running() is None:
        apps.open_app(app_name)
        for _ in range(80):
            time.sleep(0.1)
            if running() is not None:
                break
    if running() is None:
        raise ArrangeError(f"{app_name} didn't open.")
    return running()


def _window(app):
    """The app's front window."""
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
    """Usable area of each screen as (x, y, width, height), top-left origin."""
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
    AXUIElementSetAttributeValue(window, "AXPosition", position)  # some apps move it back after a resize


def _open_app_named(name: str):
    """Running app for a spoken name, without opening anything."""
    workspace = NSWorkspace.sharedWorkspace()
    if name.strip().lower() in ("", "this", "this app", "this window", "it"):
        return workspace.frontmostApplication()
    found = apps.find_app(name)
    bundle_id = NSBundle.bundleWithPath_(str(found[1])).bundleIdentifier() if found else None
    running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id) if bundle_id else []
    if not running:
        raise ArrangeError(f"{found[0] if found else name} isn't open.")
    return running[0]


def close_windows(app: str = "", which: str = "front") -> dict:
    """Close windows with their own close button. which: "front" or "all"; app "all" = every app.
    Unsaved documents still prompt to save.
    """
    if not menus.check_permission():
        raise ArrangeError("Dock needs the Accessibility permission to close windows.")
    if app.strip().lower() in ("all", "everything", "every app", "all apps"):
        targets = [a for a in NSWorkspace.sharedWorkspace().runningApplications()
                   if a.activationPolicy() == 0 and a.processIdentifier() != os.getpid()]
        which = "all"
    else:
        targets = [_open_app_named(app)]
    closed, names = 0, []
    for target in targets:
        windows = [w for w in menus._get(AXUIElementCreateApplication(target.processIdentifier()), "AXWindows") or []
                   if menus._get(w, "AXRole") == "AXWindow"]
        if which != "all":
            windows = windows[:1]
        count = 0
        for window in windows:
            button = menus._get(window, "AXCloseButton")
            if button is not None:
                AXUIElementPerformAction(button, "AXPress")
                count += 1
        if count:
            closed += count
            names.append(str(target.localizedName()))
    return {"closed": closed, "apps": names}


def clear_screen() -> dict:
    """Show the desktop: hide every app and minimize Finder windows."""
    workspace = NSWorkspace.sharedWorkspace()
    finder = next((a for a in workspace.runningApplications() if a.bundleIdentifier() == "com.apple.finder"), None)
    if finder is not None:
        finder.activateWithOptions_(0)
        time.sleep(0.2)
    hidden = 0
    for app in workspace.runningApplications():
        if (app.activationPolicy() == 0 and app != finder and app.processIdentifier() != os.getpid()
                and not app.isHidden()):
            app.hide()
            hidden += 1
    if finder is not None:
        for window in menus._get(AXUIElementCreateApplication(finder.processIdentifier()), "AXWindows") or []:
            if menus._get(window, "AXRole") == "AXWindow" and not menus._get(window, "AXMinimized"):
                AXUIElementSetAttributeValue(window, "AXMinimized", True)
                hidden += 1
    return {"cleared": hidden}


def arrange(layout: list[dict], screen: str = "this", hide_others: bool = False) -> dict:
    """layout: [{"app": "Chrome", "place": "left"}, ...]. screen: "this", "other" or "main"."""
    if not menus.check_permission():
        raise ArrangeError("Dock needs the Accessibility permission to move windows.")
    if hide_others and not layout:
        return {**clear_screen(), "arranged": [], "problems": [], "screens": len(_screens())}
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
            time.sleep(1.0)
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
