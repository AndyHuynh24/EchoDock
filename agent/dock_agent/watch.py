"""Watches the front app: sends its menus when it changes (for the shortcut pad) and
logs active time per app to ~/.dock/activity/ for the recap.
"""

import json
import os
import threading
import time
from datetime import date
from pathlib import Path

from AppKit import NSWorkspace, NSWorkspaceApplicationKey, NSWorkspaceDidActivateApplicationNotification
from Foundation import NSObject
from PyObjCTools import AppHelper
from Quartz import CGEventSourceSecondsSinceLastEventType, kCGAnyInputEventType, kCGEventSourceStateHIDSystemState

from dock_agent import link, menus

ACTIVITY_DIR = Path.home() / ".dock" / "activity"
SAMPLE_SECONDS = 30
IDLE_SECONDS = 120

_watcher = None


class _AppWatcher(NSObject):
    def appActivated_(self, notification):
        app = notification.userInfo()[NSWorkspaceApplicationKey]
        name, pid = str(app.localizedName()), int(app.processIdentifier())
        _announce_in_background(name, pid)


def start() -> None:
    """Start watching. Main thread, before the event loop."""
    global _watcher
    _watcher = _AppWatcher.alloc().init()
    NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
        _watcher, "appActivated:", NSWorkspaceDidActivateApplicationNotification, None
    )
    AppHelper.callLater(SAMPLE_SECONDS, _sample)


def announce_front_app() -> None:
    """Report the current front app."""
    name, pid = menus.front_app()
    _announce_in_background(name, pid)


def _announce_in_background(name: str, pid: int) -> None:
    if pid == os.getpid():
        return
    threading.Thread(target=_announce, args=(name, pid), daemon=True).start()


def _announce(name: str, pid: int) -> None:
    # Launching apps have no menus yet.
    items = []
    for _ in range(12):
        try:
            items = menus.read_menus(pid, use_cache=False)
        except Exception:
            items = []
        if items:
            break
        time.sleep(0.5)
    link.send_event("front_app", app=name, pid=pid, items=items)


def _sample() -> None:
    try:
        idle = CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)
        if idle < IDLE_SECONDS:
            name, _ = menus.front_app()
            _add_seconds(name, SAMPLE_SECONDS)
    except Exception as e:
        print(f"Activity sample failed: {e!r}")
    finally:
        AppHelper.callLater(SAMPLE_SECONDS, _sample)


def _activity_file(day: date) -> Path:
    return ACTIVITY_DIR / f"{day.isoformat()}.json"


def _add_seconds(app: str, seconds: int) -> None:
    path = _activity_file(date.today())
    data = json.loads(path.read_text()) if path.exists() else {}
    data[app] = data.get(app, 0) + seconds
    ACTIVITY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def minutes_by_app(day: date) -> dict[str, int]:
    path = _activity_file(day)
    seconds = json.loads(path.read_text()) if path.exists() else {}
    return {app: round(s / 60) for app, s in seconds.items()}
