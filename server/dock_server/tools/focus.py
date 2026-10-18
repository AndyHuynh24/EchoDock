"""Focus mode tools (optional; the desk assistant works without them).
See dock_server/focus.py for how focus mode works."""

import asyncio
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import calendar_link
from dock_server.calendar_link import Calendar
from dock_server.focus import FocusMode
from dock_server.notes import Notes


def register(mcp: MCPServer, focus: FocusMode, notes: Notes, calendar: Calendar, mail=None) -> None:
    @mcp.tool()
    async def start_focus_session(goal: str = "", minutes: int = 0, workspace: str = "") -> str:
        """Start a focus session on a goal, e.g. goal "stat310 homework", minutes 50.
        Leave minutes at 0 if the user didn't say a length: the session then runs
        until they end it. A saved workspace matching the goal opens automatically;
        pass workspace to open a specific one. The phone shows the goal and time,
        and its camera pauses the session when the user steps away. Open notes
        that match the goal are mentioned too, and the session ends before the
        next calendar event instead of running into it."""
        limited_by = None
        try:
            minutes, limited_by = await asyncio.to_thread(calendar.focus_limit, minutes)
        except Exception as e:
            print(f"Couldn't check the calendar: {e!r}")
        text = await focus.start(goal, minutes, workspace)
        if limited_by and text.startswith("Started"):
            text += f" It ends {calendar_link.EARLY_MINUTES} minutes before {calendar.describe(limited_by)}."
        matching = [n for n in notes.open_notes(goal) if goal and set(goal.lower().split()) & set(n["text"].lower().split())]
        if text.startswith("Started") and matching:
            text += f" From your notes: {notes.spoken_list(matching, 2)}."
        return text

    @mcp.tool()
    async def control_focus(action: Literal["pause", "resume", "break", "end"], minutes: int = 0,
                            finished_goal: bool | None = None) -> str:
        """Change the focus session that is running:
        - "pause" ("pause my session"), "resume" ("I'm back"),
        - "break": a break after a session (minutes, default about a fifth of the
          session, 5 to 15); the phone shows shortcut flashcards meanwhile,
        - "end": end it with a short report. Set finished_goal when the user says
          whether they finished (e.g. answering "did you finish your goal?")."""
        if action == "pause":
            return await focus.pause()
        if action == "resume":
            return await focus.resume()
        if action == "break":
            return await focus.start_break(minutes)
        if action == "end":
            text = await focus.end(finished_goal)
            held = mail.held_count() if mail else 0
            if held:
                text += f" {held} email{'s' if held != 1 else ''} came in while you focused. Say what did I miss."
            return text
        raise ToolError("The action must be pause, resume, break or end.")

    @mcp.tool()
    async def focus_status() -> str:
        """How the focus session running right now is going: time focused, time
        left, paused or away ("how's my session going?"). For the week, use get_recap."""
        return focus.status()
