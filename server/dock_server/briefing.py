"""Morning briefing: today's calendar, important email and open notes.

Offered once per morning, never during a focus session.
"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server.calendar_link import Calendar, _clock, is_todo
from dock_server.hub import Hub
from dock_server.mail import DEMO as mail_demo, Mail
from dock_server.notes import Notes
from dock_server.state import DATA_DIR

BRIEFING_FILE = DATA_DIR / "briefing.json"
MORNING_HOURS = (5, 12)
MAX_EVENTS = 3
# If Gmail is slow, fall back to the last read.
MAIL_WAIT_SECONDS = 3.5
MAX_NOTES = 3


class Briefing:
    def __init__(self, hub: Hub, calendar: Calendar, mail: Mail, notes: Notes, focus):
        self.hub = hub
        self.calendar = calendar
        self.mail = mail
        self.notes = notes
        self.focus = focus
        self._last_mail = mail.demo_read

    def _keep_mail(self, reading) -> None:
        if not reading.cancelled() and reading.exception() is None:
            self._last_mail = reading.result()

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

    # ---- local data ----

    def _events(self) -> list[dict]:
        if not self.calendar.connected:
            return []
        now = datetime.now()
        end = now.replace(hour=23, minute=59)
        try:
            return [e for e in self.calendar.events(now, end) if (e["all_day"] or e["end"] > now) and not is_todo(e)][:MAX_EVENTS]
        except Exception as e:
            print(f"Briefing: couldn't read the calendar: {e!r}")
            return []

    @staticmethod
    def _event_text(event: dict) -> str:
        return f"{event['title']} (all day)" if event["all_day"] else f"{event['title']} at {_clock(event['start'])}"

    # ---- morning card ----

    async def on_activity(self) -> None:
        """Offer the briefing the first time the user is at the computer each morning."""
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

    # ---- briefing ----

    async def brief(self) -> str:
        """Fill in the briefing card and return a short line to speak."""
        started = time.monotonic()
        took = {}

        async def timed(part, work):
            begun = time.monotonic()
            try:
                return await work
            finally:
                took[part] = time.monotonic() - begun

        reading_mail = asyncio.create_task(timed("email", self.mail.new_mail(
            "overnight" if datetime.now().hour < 12 else "today", everything=mail_demo))) if self.mail.connected else None
        events, notes = await asyncio.gather(timed("calendar", asyncio.to_thread(self._events)),
                                             timed("to-dos", asyncio.to_thread(self.notes.open_notes)))
        notes = notes[:MAX_NOTES]
        spoken = ["Good morning!" if datetime.now().hour < 12 else "Here's your day."]
        sections = []
        if events:
            spoken.append("Today: " + ", ".join(self._event_text(e) for e in events) + ".")
            sections.append({"title": "Today", "lines": [self._event_text(e) for e in events]})
        elif self.calendar.connected:
            spoken.append("Nothing else on your calendar today.")
        mail_items, offer = [], ""
        if reading_mail:
            try:
                # Test label: the emails don't change, so no need to wait for Gmail.
                self._last_mail = self._last_mail or self.mail.demo_read
                wait = 0 if mail_demo and self._last_mail else max(0.1, MAIL_WAIT_SECONDS - (time.monotonic() - started))
                try:
                    found = await asyncio.wait_for(asyncio.shield(reading_mail), wait)
                except asyncio.TimeoutError:
                    if self._last_mail is None:
                        found = await reading_mail
                    else:
                        if not mail_demo:
                            print("Gmail is slow: the briefing uses the email read last time")
                        reading_mail.add_done_callback(self._keep_mail)
                        found = self._last_mail
                self._last_mail = found
                spoken.append(found["spoken"])
                offer = found["offer"]
                mail_items = self.mail.card_items(found["important"])
                if mail_items or found["rest"]:
                    sections.append({"title": "Email", "mail": mail_items,
                                     "lines": [f"Also {found['rest']}."] if found["rest"] else []})
            except ToolError as e:
                spoken.append(str(e))
        if notes:
            spoken.append(f"To do: {self.notes.spoken_list(notes, MAX_NOTES)}.")
            sections.append({"title": "To do", "lines": [self.notes.describe(n) for n in notes]})
        if offer:
            spoken.append(offer)
        if len(spoken) == 1:
            return "There's nothing to brief you on yet: sign in with Google in Dock's settings to connect your calendar and email."
        await self.hub.push_phone("briefing", title="Your briefing", sections=sections, ask=False)
        print(f"Briefing ready in {time.monotonic() - started:.1f}s (" + ", ".join(f"{k} {v:.1f}s" for k, v in took.items()) + ")")
        print("Briefing (on the card, not said): " + " ".join(spoken[1:]))
        return ("Good morning! " if datetime.now().hour < 12 else "") + "Your briefing for today is ready to review."

    async def from_phone(self, message: dict) -> None:
        await self.hub.push_phone("briefing_done")
        if message.get("yes"):
            spoken = await self.brief()
            await self.hub.push_phone("say", text=spoken, show=False)

    def register(self, mcp: MCPServer) -> None:
        @mcp.tool()
        async def get_briefing() -> str:
            """The user's briefing for the day, in one go: today's calendar, the
            email that matters (important ones only, with to-dos), and their open
            notes. For "good morning", "brief me", "catch me up", "what does my
            day look like?". Just the calendar is get_schedule; just email is
            check_email."""
            return await self.brief()
