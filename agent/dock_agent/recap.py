"""Today's activity: minutes per app (from watch.py) and files changed (from Spotlight)."""

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dock_agent import watch
from dock_agent.files import HOME, _mtime, _visible, where

ROOTS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads", HOME / "Library" / "CloudStorage",
         HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs"]
MAX_FILES = 15


def _files(attribute: str, offset: int) -> list[dict]:
    start = "$time.today" if offset == 0 else f"$time.today({offset})"
    return _search(f"{attribute} >= {start} && {attribute} < $time.today({offset + 1})")


def files_changed_since(timestamp: float) -> list[dict]:
    """Files changed since `timestamp`."""
    since = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _search(f"kMDItemContentModificationDate >= $time.iso({since})")


def _search(query: str) -> list[dict]:
    command = ["mdfind"]
    for root in ROOTS:
        if root.is_dir():
            command += ["-onlyin", str(root)]
    try:
        output = subprocess.run([*command, query], capture_output=True, text=True, timeout=8).stdout
    except subprocess.TimeoutExpired:
        return []
    files = [Path(line) for line in output.splitlines() if line]
    files = [p for p in files if p.is_file() and _visible(p)]
    files.sort(key=_mtime, reverse=True)
    return [{"name": p.name, "where": where(p)} for p in files[:MAX_FILES]]


def day_recap(day: str = "today") -> dict:
    offset = -1 if day.strip().lower() == "yesterday" else 0
    the_day = date.today() + timedelta(days=offset)
    minutes = watch.minutes_by_app(the_day)
    return {
        "day": the_day.strftime("%A, %B %-d"),
        "apps": [{"app": app, "minutes": m} for app, m in sorted(minutes.items(), key=lambda kv: -kv[1]) if m > 0],
        "changed": _files("kMDItemContentModificationDate", offset),
        "opened": _files("kMDItemLastUsedDate", offset),
    }
