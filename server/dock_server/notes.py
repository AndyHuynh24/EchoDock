"""Quick capture: "note: ask the professor about Q3", "remind me to email
Nancy", "remind me to call Mom at 5", "I need to submit the form by Friday
noon", "what's on my list?", "mark email Nancy done".

Each note remembers which app and document the user was in when they said
it. Dock brings the open ones up when a focus session starts (the ones that
match the goal first) and in the day recap, and any MCP client (Alexa+ in the
kitchen too) can ask what's left. Kept in .data/notes.json.

A to-do with a time also goes on the user's Google Calendar (when Dock may add
events there, calendar_link.py): a reminder ("call Mom at 5") alerts at that
time; a deadline ("by Friday noon") is a block ending then, with an alert an
hour before. Without the calendar, Dock reminds the user itself at that time
(a card and a sound on the phone or in the Mac bubble). To-dos from email
(mail.py) come in the same way.
"""

import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.state import DATA_DIR
from dock_server.timefmt import strftime

NOTES_FILE = DATA_DIR / "notes.json"
FILLER = re.compile(r"^(note|remember|remind me|to ?do|add)( to| that)?[:,]?\s+", re.IGNORECASE)


REMIND_EARLY_MINUTES = 60  # Dock's own alert for a deadline comes this early


def parse_when(text, roll: bool = False) -> tuple[datetime, bool] | None:
    """ "2026-10-16 17:00" (or "2026-10-16" for a whole day) as (moment, all_day);
    None if there's none or it's already over. roll: a time earlier today means
    tomorrow ("remind me at 5", said at 10 pm)."""
    for form, all_day in (("%Y-%m-%d %H:%M", False), ("%Y-%m-%dT%H:%M", False), ("%Y-%m-%d", True)):
        try:
            moment = datetime.strptime(str(text or "").strip()[:16 if not all_day else 10], form)
        except ValueError:
            continue
        if roll and not all_day and moment.date() == date.today() and moment <= datetime.now():
            moment += timedelta(days=1)  # ("at 5pm", said at 10 pm: tomorrow at 5)
        if 0 < (date.today() - moment.date()).days < 31:
            moment = _next_month(moment)  # ("the 1st", said on the 16th: next month's 1st)
        over = moment + timedelta(days=1) if all_day else moment
        return (moment, all_day) if over > datetime.now() else None
    return None


def _next_month(moment: datetime) -> datetime:
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    days_in_month = ((date(year + (month == 12), month % 12 + 1, 1)) - date(year, month, 1)).days
    return moment.replace(year=year, month=month, day=min(moment.day, days_in_month))


def when_text(due: tuple[datetime, bool]) -> str:
    """ "tonight at 11:59 PM", "tomorrow at 9 AM", "Friday", "Oct 30"..."""
    moment, all_day = due
    days = (moment.date() - date.today()).days
    day = ("today" if moment.hour < 18 or all_day else "tonight") if days == 0 else "tomorrow" if days == 1 \
        else moment.strftime("%A") if days < 7 else strftime(moment, "%b %-d")
    return day if all_day else f"{day} at {strftime(moment, '%-I:%M %p').replace(':00 ', ' ')}"


def _due_of(note: dict) -> tuple[datetime, bool] | None:
    return (datetime.fromisoformat(note["due"]), note.get("all_day", False)) if note.get("due") else None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


class Notes:
    def __init__(self, hub: Hub):
        self.hub = hub
        self.calendar = None  # set by main.py once the calendar exists (it uses the notes too)
        self.items: list[dict] = json.loads(NOTES_FILE.read_text()) if NOTES_FILE.exists() else []
        self._watching = False

    def _save(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        NOTES_FILE.write_text(json.dumps(self.items, indent=1))

    def open_notes(self, about: str = "") -> list[dict]:
        """Notes not done yet; the ones that share words with `about` come first."""
        notes = [n for n in self.items if not n["done"]]
        wanted = _words(about)
        # (Then the ones with a time, soonest first.)
        return sorted(notes, key=lambda n: (-len(wanted & _words(n["text"] + " " + n.get("document", ""))), n.get("due") or "~"))

    async def add(self, text: str, when=None, deadline: bool = False) -> dict:
        """Add a note. when: "YYYY-MM-DD HH:MM" (or a (moment, all_day) pair) for a
        to-do with a time; deadline: it's due then (else it's a reminder at that time)."""
        text = FILLER.sub("", text.strip()).strip()
        if not text:
            raise ToolError("What should the note say?")
        due = when if isinstance(when, tuple) else parse_when(when, roll=not deadline) if when else None
        if when and due is None and not isinstance(when, tuple):
            # (The model then tries again with a future time: "the 1st" in late October is November 1st.)
            raise ToolError(f"{when} has already passed (it's {datetime.now():%Y-%m-%d %H:%M} now). Use a time in the future.")
        where = {}
        try:
            window = await self.hub.ask_agent("front_window")
            where = {"app": window.get("app", ""), "document": window.get("document", "").rsplit("/", 1)[-1]}
        except (AgentOffline, AgentError):
            pass
        note = {"id": int(time.time() * 1000), "text": text, "added": datetime.now().isoformat(timespec="minutes"),
                "done": False, **where}
        if due:
            note.update(due=due[0].isoformat(timespec="minutes"), all_day=due[1], deadline=deadline, on_calendar=False)
            if self.calendar and self.calendar.can_add:
                try:
                    await asyncio.to_thread(self.calendar.add_event, f"Due: {text}" if deadline else text, due[0], due[1], deadline)
                    note["on_calendar"] = True
                except Exception as e:
                    print(f"Couldn't add {text!r} to the calendar: {e!r}")  # (Dock reminds instead)
        self.items.append(note)
        self._save()
        return note

    @staticmethod
    def describe(note: dict) -> str:
        """ "submit HW4 (due tonight at 11:59 PM)", "call Mom (today at 5 PM)"."""
        due = _due_of(note)
        if not due:
            return note["text"]
        return f"{note['text']} ({'due ' if note.get('deadline') else ''}{when_text(due)})"

    def confirm(self, note: dict) -> str:
        """What Dock says after adding a note."""
        due = _due_of(note)
        if not due:
            return f"Noted: {note['text']}."
        if note.get("on_calendar"):
            if note.get("deadline"):
                return f"Okay: {self.describe(note)}. It's on your calendar, with a reminder " + ("the morning before." if due[1] else "an hour before.")
            return f"Okay: {self.describe(note)}. It's on your calendar" + (", with a reminder that morning." if due[1] else ".")
        early = " an hour before" if note.get("deadline") and not due[1] else ""
        return f"Okay: {self.describe(note)}. I'll remind you{early}."

    # ---- Dock's own reminders (for to-dos with a time that aren't on a calendar) ----

    def ensure_watch(self) -> None:
        if not self._watching:
            self._watching = True
            asyncio.get_running_loop().create_task(self._watch())

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self.check_reminders()

    async def check_reminders(self) -> None:
        now = datetime.now()
        for note in self.open_notes():
            due = _due_of(note)
            if not due or note.get("on_calendar") or note.get("reminded"):
                continue
            moment, all_day = due
            alert = moment.replace(hour=9, minute=0) if all_day else \
                moment - timedelta(minutes=REMIND_EARLY_MINUTES) if note.get("deadline") else moment
            if now >= alert:
                note["reminded"] = True
                self._save()
                await self.hub.push_phone("tip", title=f"Reminder: {note['text']}"[:60],
                                          detail=("Due " + when_text(due)) if note.get("deadline") else "", sound=True)

    def done(self, text: str) -> dict | None:
        """Mark the open note that best matches `text` as done."""
        wanted = _words(text)
        best = max(self.open_notes(), key=lambda n: len(wanted & _words(n["text"])), default=None)
        if best is None or not wanted & _words(best["text"]):
            return None
        best["done"] = True
        self._save()
        return best

    def spoken_list(self, notes: list[dict], limit: int = 5) -> str:
        if not notes:
            return ""
        parts = [self.describe(n) for n in notes[:limit]]
        more = f", and {len(notes) - limit} more" if len(notes) > limit else ""
        return "; ".join(parts) + more

    def register(self, mcp: MCPServer) -> None:
        @mcp.tool()
        async def notes(action: Literal["add", "list", "done"], text: str = "", when: str = "",
                        deadline: bool = False) -> str:
            """Quick notes, to-dos and reminders, without opening an app:
            - "add": "note: ask the professor about Q3", "remind me to email Nancy",
              "add buy printer ink to my list" (text = the note, without the time).
              With a time ("remind me to call Mom at 5", "I need to submit the form
              by Friday noon", "pay rent on the 1st"): when = "YYYY-MM-DD HH:MM" (or
              "YYYY-MM-DD" for a whole day, 24-hour time), worked out from the date
              and time now, and always in the future: a time of day that has passed
              today means tomorrow, a day of the month that has passed means next
              month. deadline true when it's due then ("by", "before", "due"), false
              for a reminder at that time. It also goes on their calendar, or Dock
              reminds them itself.
            - "list": "what's on my list?", "what's left for tomorrow?", "any notes?",
            - "done": "mark email Nancy done", "I did the Q3 question" (text = which one).
            Each note remembers the app and document the user was in. Open notes come
            up again when a focus session starts, in the morning briefing and in the
            day recap."""
            if action == "add":
                note = await self.add(text, when, deadline)
                await self.hub.push_phone("toast", text=f"✓ {self.describe(note)}"[:60])
                return self.confirm(note)
            if action == "done":
                note = self.done(text)
                if note is None:
                    raise ToolError("I couldn't find a note like that on your list.")
                left = len(self.open_notes())
                return f"Done: {note['text']}." + (f" {left} left on your list." if left else " Your list is clear.")
            open_now = self.open_notes()
            if not open_now:
                return "Your list is empty."
            await self.hub.push_phone("card", title=f"Your list ({len(open_now)})",
                                      detail="\n".join(f"• {self.describe(n)}" for n in open_now[:8]))
            return f"You have {len(open_now)} on your list: {self.spoken_list(open_now)}."
