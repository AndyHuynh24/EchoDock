"""Watches which app is in front, on Windows (the same as dock_agent/watch.py):

- When the app in front changes, the server gets that app's menus (only
  those Windows can list without opening anything), for the phone's
  shortcut pad.
- Every 30 seconds, if the user is active (touched the keyboard or mouse in
  the last 2 minutes), the app in front gets 30 seconds of use. This feeds the
  end-of-day recap. Saved only on this computer, in ~/.dock/activity/.
"""

import json
import threading
import time
from datetime import date
from pathlib import Path

from dock_agent import link
from dock_agent.win import menus, uia, winapi

ACTIVITY_DIR = Path.home() / ".dock" / "activity"
CHECK_SECONDS = 0.5
SAMPLE_SECONDS = 30
IDLE_SECONDS = 120


def start() -> None:
    threading.Thread(target=_watch, daemon=True, name="front app").start()


def announce_front_app() -> None:
    """Tell the server which app is in front right now (e.g. after reconnecting)."""
    name, pid = menus.front_app()
    if pid:
        threading.Thread(target=_announce, args=(name, pid), daemon=True).start()


def _announce(name: str, pid: int) -> None:
    uia.ready()
    items = []
    for _ in range(6):  # an app that is still starting has no menus yet
        try:
            items = menus.read_menus(pid, use_cache=False, open_menus=False)
        except Exception:
            items = []
        if items:
            break
        time.sleep(0.5)
    link.send_event("front_app", app=name, pid=pid, items=items)


def _watch() -> None:
    uia.ready()
    last_pid, sampled = 0, time.time()
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            name, pid = menus.front_app()
            if pid and pid != last_pid:
                last_pid = pid
                threading.Thread(target=_announce, args=(name, pid), daemon=True).start()
            if time.time() - sampled >= SAMPLE_SECONDS:
                sampled = time.time()
                if winapi.idle_seconds() < IDLE_SECONDS and pid:
                    _add_seconds(name, SAMPLE_SECONDS)
        except Exception as e:
            print(f"Front app check failed: {e!r}")


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
