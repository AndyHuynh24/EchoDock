"""The morning briefing: today's calendar, the email that matters, and the
user's open notes, in one card and a few spoken sentences.

- The first time the user is at the computer each morning (MORNING_HOURS; a
  window change on the Mac, or the phone connecting), a card shows what's
  known for free: the next events and the open notes, and how many new
  emails there are. "Brief me" (or saying "good morning" / "brief me" any
  time, get_briefing) reads it out, with the important emails sorted by the
  AI (mail.py); an email's to-do can be added to the list from the card.
- Once a day at most, and never during a focus session. It can be turned off
  in settings.
- Anything that isn't connected (calendar, email) is simply left out.
"""

import asyncio
import json
from datetime import date, datetime, timedelta

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server.calendar_link import Calendar, _clock
from dock_server.hub import Hub
from dock_server.mail import Mail
from dock_server.notes import Notes
from dock_server.state import DATA_DIR

BRIEFING_FILE = DATA_DIR / "briefing.json"
MORNING_HOURS = (5, 12)  # the card is offered between these hours
MAX_EVENTS = 3
MAX_NOTES = 3


class Briefing:
    def __init__(self, hub: Hub, calendar: Calendar, mail: Mail, notes: Notes, focus):
        self.hub = hub
        self.calendar = calendar
        self.mail = mail
        self.notes = notes
        self.focus = focus

    def _settings(self) -> dict:
        return json.loads(BRIEFING_FILE.read_text()) if BRIEFING_FILE.exists() else {}

    def _set(self, **values) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        BRIEFING_FILE.write_text(json.dumps({**self._settings(), **values}, indent=2))

    @property
    def on(self) -> bool:
        return self._settings().get("on", True)

    def set_on(self, on: bool) -> None:
        self._set(on=on)

    # ---- What's known without AI ----

    def _events(self) -> list[dict]:
        if not self.calendar.connected:
            return []
        now = datetime.now()
        end = now.replace(hour=23, minute=59)
        try:
            return [e for e in self.calendar.events(now, end) if e["all_day"] or e["end"] > now][:MAX_EVENTS]
        except Exception as e:
            print(f"Briefing: couldn't read the calendar: {e!r}")
            return []

    @staticmethod
    def _event_text(event: dict) -> str:
        return f"{event['title']} (all day)" if event["all_day"] else f"{event['title']} at {_clock(event['start'])}"

    # ---- The morning card ----

    async def on_activity(self) -> None:
        """The user is at the computer. The first time each morning: offer the briefing."""
        today = date.today().isoformat()
        if (not MORNING_HOURS[0] <= datetime.now().hour < MORNING_HOURS[1] or not self.on
                or self._settings().get("offered") == today or (self.focus.session or {}).get("state") == "running"):
            return
        self._set(offered=today)
        events = await asyncio.to_thread(self._events)
        notes = self.notes.open_notes()[:MAX_NOTES]
        new_mail = 0
        if self.mail.connected:
            try:
                new_mail = await asyncio.to_thread(self.mail.unread_count, datetime.now() - timedelta(hours=18))
            except Exception as e:
                print(f"Briefing: couldn't check email: {e!r}")
        if not (events or notes or new_mail):
            return
        sections = []
        if events:
            sections.append({"title": "Today", "lines": [self._event_text(e) for e in events]})
        if new_mail:
            sections.append({"title": "Email", "lines": [f"{new_mail} new since last night"]})
        if notes:
            sections.append({"title": "On your list", "lines": [n["text"] for n in notes]})
        await self.hub.push_phone("briefing", title="Good morning!", sections=sections, ask=True)

    # ---- Reading it out ----

    async def brief(self) -> str:
        """The whole briefing, spoken, with the card filled in (important emails and their to-dos)."""
        events = await asyncio.to_thread(self._events)
        notes = self.notes.open_notes()[:MAX_NOTES]
        spoken = ["Good morning." if datetime.now().hour < 12 else "Here's your day."]
        sections = []
        if events:
            spoken.append("Today: " + ", ".join(self._event_text(e) for e in events) + ".")
            sections.append({"title": "Today", "lines": [self._event_text(e) for e in events]})
        elif self.calendar.connected:
            spoken.append("Nothing else on your calendar today.")
        mail_items, offer = [], ""
        if self.mail.connected:
            try:
                found = await self.mail.new_mail("overnight" if datetime.now().hour < 12 else "today")
                spoken.append(found["spoken"])
                offer = found["offer"]  # (asked last, after the list)
                mail_items = self.mail.card_items(found["important"])
                if mail_items or found["rest"]:
                    sections.append({"title": "Email", "mail": mail_items,
                                     "lines": [f"Also {found['rest']}."] if found["rest"] else []})
            except ToolError as e:
                spoken.append(str(e))
        if notes:
            spoken.append(f"On your list: {self.notes.spoken_list(notes, MAX_NOTES)}.")
            sections.append({"title": "On your list", "lines": [n["text"] for n in notes]})
        if offer:
            spoken.append(offer)
        if len(spoken) == 1:
            return "There's nothing to brief you on yet: sign in with Google in Dock's settings to connect your calendar and email."
        await self.hub.push_phone("briefing", title="Your briefing", sections=sections, ask=False)
        return " ".join(spoken)

    async def from_phone(self, message: dict) -> None:
        await self.hub.push_phone("briefing_done")  # (answered on one screen: gone from the others)
        if message.get("yes"):
            spoken = await self.brief()
            await self.hub.push_phone("say", text=spoken, show=False)  # (the card shows it already)

    def register(self, mcp: MCPServer) -> None:
        @mcp.tool()
        async def get_briefing() -> str:
            """The user's briefing for the day, in one go: today's calendar, the
            email that matters (important ones only, with to-dos), and their open
            notes. For "good morning", "brief me", "catch me up", "what does my
            day look like?". Just the calendar is get_schedule; just email is
            check_email."""
            return await self.brief()
