"""Recaps: which apps the user spent time in, which files they worked on,
what they asked Dock, and how much time Dock saved them (see savings.py for
how that's counted)."""

import asyncio
from datetime import date, timedelta
from typing import Literal

from mcp.server import MCPServer

from dock_server import bedrock
from dock_server.focus import FocusMode
from dock_server.notes import Notes
from dock_server.hub import Hub
from dock_server.savings import Savings
from dock_server.state import State
from dock_server.tools.computer import run_on_computer

RECAP_SYSTEM = (
    "Write a friendly end-of-day recap for a student, to be spoken out loud: 3 or 4 short "
    "sentences. Mention where most of their time went (rounded times), the main projects "
    "or classes they worked on (guess from folder and file names), mention the time Dock saved "
    "them if there is any, say briefly what's still on their list if anything, and end with one "
    "short, encouraging suggestion. No markdown, lists, file paths or emojis."
)


def _hours(minutes: int) -> str:
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def time_saved(savings: Savings, days: int) -> str:
    period = "today" if days == 1 else "this week" if days == 7 else f"in the last {days} days"
    summary = savings.summary(days)
    if not summary:
        return f"Dock hasn't saved you any time {period} yet. Ask me where something is in an app, or to open a folder."
    return f"{period.capitalize()} Dock saved you {summary}."


def register(mcp: MCPServer, hub: Hub, state: State, savings: Savings, focus: FocusMode, notes: Notes) -> None:
    @mcp.tool()
    async def get_recap(period: Literal["today", "yesterday", "week"] = "today") -> str:
        """A recap of the user's work:
        - "today" or "yesterday": time spent per app, the files they worked on,
          what they asked Dock, and time Dock saved ("what did I work on today?",
          "give me my end-of-day recap"),
        - "week": the last 7 days: focus sessions (total time, goals finished,
          best day; also a chart on the phone) and how much time Dock saved them
          and how ("how was my week?", "how much time did Dock save me?", "how
          am I doing with shortcuts?")."""
        if period == "week":
            return f"{await focus.week_report()} {time_saved(savings, 7)}"
        day = period
        recap = await run_on_computer(hub, "day_recap", timeout=15, day=day)
        the_day = date.today() - timedelta(days=1 if day.strip().lower() == "yesterday" else 0)
        asked = [item for d, _app, item in state.questions if d == the_day]

        lines = [f"Day: {recap['day']}"]
        if recap["apps"]:
            lines.append("Time per app: " + ", ".join(f"{a['app']} {_hours(a['minutes'])}" for a in recap["apps"][:6]))
        else:
            lines.append("Time per app: not recorded (the Dock agent wasn't running).")
        if recap["changed"]:
            lines.append("Files changed: " + ", ".join(f"{f['name']} ({f['where']})" for f in recap["changed"]))
        if recap["opened"]:
            lines.append("Files opened: " + ", ".join(f"{f['name']} ({f['where']})" for f in recap["opened"]))
        if asked:
            lines.append("Asked Dock about: " + ", ".join(dict.fromkeys(asked)))
        if the_day == date.today() and savings.summary(1):
            lines.append("Time Dock saved them today: " + savings.summary(1))
        if notes.open_notes():
            lines.append("Still on their list: " + notes.spoken_list(notes.open_notes(), 3))

        text = await asyncio.to_thread(bedrock.ask, "\n".join(lines), RECAP_SYSTEM, 300)
        await hub.push_phone("recap", day=recap["day"], apps=recap["apps"][:6], files=recap["changed"][:6], summary=text)
        return text
