"""Today's activity on Windows: minutes per app (watch.py), files changed, and files
opened (from the Recent folder).
"""

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dock_agent.files import HOME, SKIP_PARTS, _mtime, _visible, where
from dock_agent.win import watch, winapi

ROOTS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads", HOME / "OneDrive"]
MAX_FILES = 15
MAX_DEPTH = 6
MAX_SECONDS = 3


def _changed_between(start: float, end: float) -> list[Path]:
    found, deadline = [], time.time() + MAX_SECONDS
    for root in ROOTS:
        if not root.is_dir():
            continue
        base = len(root.parts)
        for folder, subfolders, names in os.walk(root):
            if time.time() > deadline:
                break
            subfolders[:] = [s for s in subfolders if not s.startswith(".") and s not in SKIP_PARTS]
            if len(Path(folder).parts) - base >= MAX_DEPTH:
                subfolders.clear()
            for name in names:
                path = Path(folder) / name
                if start <= _mtime(path) < end and not name.startswith(("~$", ".")):
                    found.append(path)
    return found


def _listed(paths: list[Path]) -> list[dict]:
    paths = [p for p in dict.fromkeys(paths) if p.is_file() and _visible(p)]
    paths.sort(key=_mtime, reverse=True)
    return [{"name": p.name, "where": where(p)} for p in paths[:MAX_FILES]]


def files_changed_since(timestamp: float) -> list[dict]:
    return _listed(_changed_between(timestamp, time.time() + 1))


def day_recap(day: str = "today") -> dict:
    offset = -1 if day.strip().lower() == "yesterday" else 0
    the_day = date.today() + timedelta(days=offset)
    start = datetime.combine(the_day, datetime.min.time()).timestamp()
    end = start + 24 * 3600
    minutes = watch.minutes_by_app(the_day)
    opened = [path for when, path in winapi.recent_files() if start <= when < end]
    return {
        "day": f"{the_day:%A, %B} {the_day.day}",
        "apps": [{"app": app, "minutes": m} for app, m in sorted(minutes.items(), key=lambda kv: -kv[1]) if m > 0],
        "changed": _listed(_changed_between(start, end)),
        "opened": _listed(opened),
    }
