"""Google Calendar: schedule, get-ready, event heads-ups, and adding to-dos when asked."""

import asyncio
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import google_account
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.notes import Notes
from dock_server.timefmt import strftime

GOOGLE_API = "https://www.googleapis.com/calendar/v3"
CACHE_SECONDS = 300
EARLY_MINUTES = 10
TODO_MINUTES = 30  # to-do block length, ending at its deadline
TODO_REMIND_MINUTES = 60
REMINDER_MINUTES = 15
MORNING_REMINDER_HOUR = 9
DAY_BEFORE_MINUTES = 15 * 60
# Calendar to-dos double as Dock's list (notes.py).
WORK = re.compile(r"\b(homework|hw\s?\d*|assignments?|essays?|papers?|reports?|projects?|proposals?|exams?|quiz(zes)?|"
                  r"midterms?|finals?|due|submit|deadlines?|labs?|problem sets?|psets?)\b", re.IGNORECASE)
NOT_WORK = re.compile(r"\b(meetings?|presentations?|reviews?|check-?ins?|1:1|calls?|class(es)?|lectures?|office hours|"
                      r"interviews?|seminars?)\b", re.IGNORECASE)
LINK = re.compile(r"https://[^\s<>\"']*(?:meet\.google\.com|zoom\.us|teams\.microsoft\.com|webex\.com)[^\s<>\"']*")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+", text.lower()))


def is_todo(event: dict) -> bool:
    """A to-do Dock added, or an event named like a task."""
    return event.get("dock", False) or (bool(WORK.search(event["title"])) and not NOT_WORK.search(event["title"]))


def _clock(moment: datetime) -> str:
    return strftime(moment, "%-I:%M %p").replace(":00 ", " ")


class Calendar:
    def __init__(self, hub: Hub, notes: Notes):
        self.hub = hub
        self.notes = notes
        self._told: set[str] = set()
        self._google_cache: dict = {}

    @property
    def connected(self) -> str:
        """"google", or "" if not connected."""
        return "google" if google_account.has(google_account.CALENDAR_READ) else ""

    def _google_session(self):
        from google.auth.transport.requests import AuthorizedSession
        return AuthorizedSession(google_account.credentials())

    def _google_events(self, start: datetime, end: datetime) -> list[dict]:
        key = (start.isoformat(), end.isoformat())
        cached = self._google_cache.get(key)
        if cached and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]
        session = self._google_session()
        calendars = session.get(f"{GOOGLE_API}/users/me/calendarList", timeout=15).json().get("items", [])
        found = []
        for calendar in calendars:
            if not calendar.get("selected", calendar.get("primary", False)):
                continue
            reply = session.get(f"{GOOGLE_API}/calendars/{urllib.parse.quote(calendar['id'])}/events", timeout=15, params={
                "timeMin": start.astimezone().isoformat(), "timeMax": end.astimezone().isoformat(),
                "singleEvents": "true", "orderBy": "startTime", "maxResults": 100}).json()
            for item in reply.get("items", []):
                if item.get("status") == "cancelled":
                    continue
                all_day = "date" in item.get("start", {})
                if all_day:
                    begins = datetime.fromisoformat(item["start"]["date"])
                    ends = datetime.fromisoformat(item.get("end", {}).get("date", item["start"]["date"]))
                else:
                    begins = datetime.fromisoformat(item["start"]["dateTime"]).astimezone().replace(tzinfo=None)
                    ends = datetime.fromisoformat(item["end"]["dateTime"]).astimezone().replace(tzinfo=None)
                video = [e["uri"] for e in item.get("conferenceData", {}).get("entryPoints", []) if e.get("entryPointType") == "video"]
                link = item.get("hangoutLink") or (video[0] if video else "")
                if not link:
                    match = LINK.search(" ".join(str(item.get(k, "")) for k in ("location", "description")))
                    link = match.group() if match else ""
                found.append({"id": f"{item['id']}@{begins.isoformat()}", "title": item.get("summary", "Untitled"),
                              "start": begins, "end": ends, "all_day": all_day,
                              "where": str(item.get("location", ""))[:80], "link": link,
                              "dock": str(item.get("description", "")).startswith("Added by Dock")})
        found.sort(key=lambda e: e["start"])
        self._google_cache[key] = (time.time(), found)
        return found

    @property
    def can_add(self) -> bool:
        return google_account.has(google_account.CALENDAR_ADD)

    def add_event(self, title: str, due: datetime, all_day: bool = False, deadline: bool = True) -> dict:
        """Add a to-do to the main calendar: a deadline block, a timed reminder, or an all-day event."""
        if not self.can_add:
            raise ToolError("To add things to your calendar, sign in with Google in Dock's settings and allow Calendar.")
        if all_day and not deadline:
            due, all_day = due.replace(hour=MORNING_REMINDER_HOUR, minute=0), False
        if all_day:
            when = {"start": {"date": due.date().isoformat()}, "end": {"date": (due.date() + timedelta(days=1)).isoformat()}}
        elif deadline:
            when = {"start": {"dateTime": (due - timedelta(minutes=TODO_MINUTES)).astimezone().isoformat()},
                    "end": {"dateTime": due.astimezone().isoformat()}}
        else:
            when = {"start": {"dateTime": due.astimezone().isoformat()},
                    "end": {"dateTime": (due + timedelta(minutes=REMINDER_MINUTES)).astimezone().isoformat()}}
        # 9 AM the day before an all-day deadline.
        remind = DAY_BEFORE_MINUTES if all_day else TODO_REMIND_MINUTES if deadline else 0
        body = {"summary": title, "description": "Added by Dock.",
                "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": remind}]}, **when}
        reply = self._google_session().post(f"{GOOGLE_API}/calendars/primary/events", json=body, timeout=15)
        if reply.status_code == 403:
            raise ToolError("Google Calendar didn't let Dock add events. Sign in with Google again in Dock's settings to allow it.")
        reply.raise_for_status()
        self._google_cache.clear()
        return reply.json()

    def events(self, start: date | datetime, end: date | datetime) -> list[dict]:
        if not self.connected:
            return []
        as_time = lambda d: d if isinstance(d, datetime) else datetime.combine(d, datetime.min.time())
        return self._google_events(as_time(start), as_time(end))

    def todos(self, days: int = 7) -> list[dict]:
        """Calendar to-dos from today through the next `days` days."""
        if not self.connected:
            return []
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            return [e for e in self.events(today, today + timedelta(days=days)) if is_todo(e)]
        except Exception as e:
            print(f"Couldn't read the to-dos on the calendar: {e!r}")
            return []

    def upcoming(self, hours: float = 12) -> list[dict]:
        now = datetime.now()
        return [e for e in self.events(now - timedelta(hours=2), now + timedelta(hours=hours))
                if not e["all_day"] and e["end"] > now]

    def next_event(self) -> dict | None:
        now = datetime.now()
        later = [e for e in self.upcoming() if e["start"] > now]
        return later[0] if later else None

    def focus_limit(self, minutes: int) -> tuple[int, dict | None]:
        """Minutes a focus session may run before the next event (0 = no limit), and that event."""
        coming = self.next_event()
        if coming is None:
            return minutes, None
        room = int((coming["start"] - datetime.now()).total_seconds() // 60) - EARLY_MINUTES
        if room < 5:
            return minutes, None
        if minutes == 0 or minutes > room:
            return room, coming
        return minutes, None

    def describe(self, event: dict) -> str:
        if event["all_day"]:
            return f"{event['title']} (all day)"
        return f"{event['title']} at {_clock(event['start'])}"

    def ensure_watch(self) -> None:
        if not getattr(self, "_watching", False):
            self._watching = True
            asyncio.get_running_loop().create_task(self.watch())

    async def watch(self) -> None:
        """Heads-up EARLY_MINUTES before each event."""
        while True:
            await asyncio.sleep(60)
            try:
                coming = await asyncio.to_thread(self.next_event) if self.connected else None
            except Exception as e:
                print(f"Calendar check failed: {e!r}")
                continue
            if not coming or coming["id"] in self._told:
                continue
            minutes = (coming["start"] - datetime.now()).total_seconds() / 60
            if 0 < minutes <= EARLY_MINUTES:
                self._told.add(coming["id"])
                await self.hub.push_phone("card", title=f"{coming['title']} in {round(minutes)} min",
                                          detail="Say \"get ready\" and Dock opens what you need.")

    def voice_context(self) -> str:
        try:
            coming = self.next_event() if self.connected else None
        except Exception:
            return ""
        if not coming:
            return ""
        return (f" Next on the user's calendar: {coming['title']} at {_clock(coming['start'])}"
                + (f" (online: {coming['link']})" if coming["link"] else "") + ".")

    def register(self, mcp: MCPServer) -> None:
        @mcp.tool()
        async def get_schedule(day: Literal["today", "tomorrow", "next"] = "today") -> str:
            """What's on the user's calendar: "today" ("what's on today?"),
            "tomorrow", or "next" ("what's next?", "when's my next class?")."""
            if not self.connected:
                raise ToolError("Your calendar isn't connected yet. Open Dock's settings and click Sign in with Google.")
            if day == "next":
                coming = await asyncio.to_thread(self.next_event)
                if not coming:
                    return "Nothing else on your calendar for the next 12 hours."
                minutes = round((coming["start"] - datetime.now()).total_seconds() / 60)
                when = f"in {minutes} minutes" if minutes < 90 else f"at {_clock(coming['start'])}"
                return f"Next is {coming['title']} {when}." + (" It has a meeting link; say get ready to open it." if coming["link"] else "")
            first = date.today() + timedelta(days=1 if day == "tomorrow" else 0)
            events = await asyncio.to_thread(self.events, first, first + timedelta(days=1))
            if not events:
                return f"Nothing on your calendar {day}."
            await self.hub.push_phone("card", title=f"{day.capitalize()} ({len(events)})",
                                      detail="\n".join(("All day" if e["all_day"] else _clock(e["start"])) + f" · {e['title']}" for e in events))
            return f"{day.capitalize()} you have " + "; ".join(self.describe(e) for e in events[:6]) + "."

        @mcp.tool()
        async def get_ready(for_what: str = "") -> str:
            """Set the computer up for something in one go: "get ready for stat
            class", "get ready for my next meeting", or just "get ready" (the next
            calendar event). Opens the event's Meet/Zoom link, the matching folder
            or saved workspace (e.g. STAT 310 → the stat310 folder), and mentions
            notes about it. Works without a calendar too ("get ready for CS589")."""
            event = None
            if self.connected:
                upcoming = await asyncio.to_thread(self.upcoming)
                wanted = _words(for_what) - {"my", "the", "next", "class", "meeting", "for", "lecture"}
                matching = [e for e in upcoming if wanted and wanted & _words(e["title"].replace(" ", "") + " " + e["title"])]
                event = matching[0] if matching else (upcoming[0] if upcoming and not wanted else None)
            topic = event["title"] if event else for_what
            if not topic.strip():
                raise ToolError("Get ready for what? Nothing is coming up on your calendar.")
            done = []
            try:
                if event and event["link"]:
                    await self.hub.ask_agent("open_url", url=event["link"])
                    done.append("the meeting link")
                place = await self._open_for(topic)
                if place:
                    done.append(place)
            except AgentOffline:
                raise ToolError("Your computer isn't connected to Dock right now.")
            related = [n for n in self.notes.open_notes(topic) if _words(topic) & _words(n["text"])]
            text = f"Ready for {self.describe(event) if event else topic}." if done else f"I didn't find anything to open for {topic}."
            if done:
                text = text[:-1] + ": I opened " + " and ".join(done) + "."
            if related:
                text += f" From your notes: {self.notes.spoken_list(related, 2)}."
            await self.hub.push_phone("toast", text=f"✓ Ready for {topic[:30]}")
            return text

    async def _open_for(self, topic: str) -> str:
        """Open the workspace or folder that matches the event (STAT 310 Lecture -> stat310)."""
        squashed = re.sub(r"\s+(?=\d)", "", topic)
        try:
            names = (await self.hub.ask_agent("list_workspaces"))["names"]
            for name in names:
                if _words(name) <= _words(squashed) | _words(topic):
                    await self.hub.ask_agent("open_workspace", timeout=30, name=name)
                    return f"your {name} workspace"
        except AgentError:
            pass
        for candidate in re.findall(r"[A-Za-z]+\d+[A-Za-z]?", squashed) + [topic]:
            try:
                found = await self.hub.ask_agent("find_folder", timeout=15, name=candidate)
                if found.get("folder"):
                    await self.hub.ask_agent("open_folder", timeout=15, name=found["folder"])
                    return f"your {found['folder']} folder"
            except AgentError:
                continue
        return ""
