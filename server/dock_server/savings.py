"""Rough, conservative estimate of time Dock saved, stored per day in .data/savings.json."""

import json
from datetime import date, timedelta

from dock_server.hub import Hub
from dock_server.state import DATA_DIR

SAVINGS_FILE = DATA_DIR / "savings.json"

# Seconds saved per action.
SECONDS = {
    "found": 20,
    "clicked": 3,
    "opened": 5,
    "workspace_app": 5,
    "file_moved": 5,
    "save_folder": 8,
    "arranged": 6,
}

WHAT = {
    "found": ("found {n} thing", "found {n} things"),
    "clicked": ("clicked {n} menu item for you", "clicked {n} menu items for you"),
    "opened": ("opened {n} folder, file or app", "opened {n} folders, files and apps"),
    "workspace_app": ("reopened {n} app in a workspace", "reopened {n} apps in workspaces"),
    "file_moved": ("tidied {n} file", "tidied {n} files"),
    "save_folder": ("picked the folder for {n} save", "picked the folder for {n} saves"),
    "arranged": ("arranged {n} window", "arranged {n} windows"),
}


def _minutes_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if seconds and minutes == 0:
        return "under a minute"
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


class Savings:
    def __init__(self, hub: Hub):
        self.hub = hub
        self.days: dict[str, dict[str, int]] = json.loads(SAVINGS_FILE.read_text()) if SAVINGS_FILE.exists() else {}

    async def add(self, kind: str, n: int = 1) -> None:
        """Record an action and update the phone."""
        if n <= 0:
            return
        today = self.days.setdefault(date.today().isoformat(), {})
        today[kind] = today.get(kind, 0) + n
        DATA_DIR.mkdir(exist_ok=True)
        SAVINGS_FILE.write_text(json.dumps(self.days, indent=2))
        await self.push()

    def totals(self, days: int = 7) -> dict[str, int]:
        """Counts for the last `days` days."""
        first = (date.today() - timedelta(days=days - 1)).isoformat()
        totals: dict[str, int] = {}
        for day, counts in self.days.items():
            if day >= first:
                for kind, n in counts.items():
                    totals[kind] = totals.get(kind, 0) + n
        return totals

    def seconds(self, days: int = 7) -> int:
        return sum(SECONDS.get(kind, 0) * n for kind, n in self.totals(days).items())

    def summary(self, days: int = 7) -> str:
        totals = self.totals(days)
        parts = [WHAT[kind][n != 1].format(n=n) for kind, n in sorted(totals.items(), key=lambda kv: -SECONDS.get(kv[0], 0) * kv[1])
                 if kind in WHAT and n]
        if not parts:
            return ""
        listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
        saved = _minutes_text(self.seconds(days))
        return f"{'' if saved.startswith('under') else 'about '}{saved}. It {listed}"

    async def push(self, ws=None) -> None:
        """Summary line shown on the phone."""
        seconds = self.seconds(7)
        message = {"kind": "savings", "week": _minutes_text(seconds) if seconds else "", "today": _minutes_text(self.seconds(1))}
        if ws is not None:
            await ws.send_text(json.dumps(message))
        else:
            await self.hub.push_phone(**message)
