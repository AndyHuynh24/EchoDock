"""Email features: catch-up summaries, inbox clean-up, unsubscribe, to-dos from email,
and holding mail during focus sessions.

Gmail is read over IMAP with the Google sign-in (XOAUTH2). The mailbox is opened
read-only unless the user approves a clean-up. Dock never sends or replies to email.
Settings are stored in .data/mail.json.
"""

import asyncio
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from html import unescape
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import bedrock
from dock_server import google_account
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.notes import parse_when as _due, when_text as _when
from dock_server.state import DATA_DIR
from dock_server.timefmt import strftime

MAIL_FILE = DATA_DIR / "mail.json"
GMAIL_IMAP = "imap.gmail.com"
# Inbox, or a Gmail label (labels are IMAP folders). Set by scripts/start.sh.
MAIL_FOLDER = os.environ.get("DOCK_MAIL_FOLDER") or "INBOX"
# With a test label, every email in it counts as new.
DEMO = MAIL_FOLDER != "INBOX"
MAX_MESSAGES = 25
MAX_CLEANUP = 60
CLEANUP_DAYS = 30
MAX_FULL_BYTES = 300_000  # larger emails: headers only
SNIPPET_CHARS = 300
CHECK_SECONDS = 120
KINDS = ("important", "update", "promotion", "spam")
SPOKEN_IMPORTANT = 2

SORT_SYSTEM = (
    "You sort someone's email. For each email decide its kind:\n"
    "- important: from a real person, or something they need to know or act on: deadlines, changes "
    "of plans, bills or payments due, real account or security alerts, school or work. These count "
    "as important even when an automatic address sends them.\n"
    "- update: automatic but maybe useful: receipts, shipping, notifications, newsletters.\n"
    "- promotion: ads, sales, marketing.\n"
    "- spam: junk, scams, phishing.\n"
    "Also: urgent (needs attention today), gist (what it is about, at most 8 words, said so it "
    "reads well after the sender's name, like \"moved the HW4 deadline to tonight\") and, for "
    "updates only, a short folder name to file it under (Receipts, Shipping, School, Work, Bills, "
    "Travel, Notifications, Newsletters, ...). For important emails that ask the user to do something "
    "by a certain time, todo: a short to-do without the time (\"Submit STAT 525 HW4\") and due: the "
    "deadline as \"YYYY-MM-DD HH:MM\" (24-hour, local time; \"YYYY-MM-DD\" if only the day is known); "
    "otherwise both are empty. The first line says what day and time it is now.\n"
    "Each email starts with its number, like [E3].\n"
    'Reply with only JSON: {"emails": [{"id": "E1", "kind": "important", '
    '"urgent": false, "gist": "...", "folder": "", "todo": "", "due": ""}, ...]} with one entry for every email, in order.'
)
URGENT_SYSTEM = (
    "Someone is concentrating. Is this email urgent enough to interrupt them now (an emergency, a "
    "deadline today, someone waiting on them right now)? Most email is not. "
    'Reply with only JSON: {"urgent": true or false, "why": "a few words"}'
)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    return "".join(part.decode(charset or "utf-8", "replace") if isinstance(part, bytes) else part
                   for part, charset in email.header.decode_header(value)).strip()


def _text_of(message: email.message.Message) -> str:
    """Start of the email's text (plain part, or HTML without tags)."""
    plain, html = "", ""
    for part in message.walk() if message.is_multipart() else [message]:
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html") or part.get_filename():
            continue
        try:
            text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if kind == "text/plain" and not plain:
            plain = text
        elif kind == "text/html" and not html:
            html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
            html = unescape(re.sub(r"<[^>]+>", " ", html))
    return " ".join((plain or html).split())[:SNIPPET_CHARS]


def _json(answer: str) -> dict:
    match = re.search(r"\{.*\}", answer, re.S)
    try:
        return json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        return {}


def _folder_name(name: str) -> str:
    """A safe, short folder name."""
    name = re.sub(r"[^A-Za-z0-9 &-]", "", str(name)).strip()[:30]
    return name.title() if name else "Updates"


def _counted(counts: dict) -> str:
    words = {"update": ("update", "updates"), "promotion": ("promotion", "promotions"), "spam": ("spam email", "spam emails"),
             "important": ("important email", "important emails")}
    parts = [f"{n} {words[k][n != 1]}" for k, n in counts.items() if n]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}" if parts else ""


def _unsubscribe_info(message) -> dict:
    """Unsubscribe info from List-Unsubscribe headers: URL and RFC 8058 one-click support."""
    links = re.findall(r"<([^>]+)>", _decode(message["List-Unsubscribe"]))
    web = next((link for link in links if link.lower().startswith("https://")), "")
    one_click = "one-click" in str(message["List-Unsubscribe-Post"] or "").lower()
    return {"unsubscribe_url": web, "one_click": bool(web) and one_click}


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Mail:
    def __init__(self, hub: Hub, focus, notes, calendar):
        self.hub = hub
        self.focus = focus
        self.notes = notes
        self.calendar = calendar
        self.offered_todos: list[dict] = []
        self._seen_in_focus: set[str] = set()
        self._sorted: dict[str, dict] = {}  # model results by Message-ID
        self.demo_read = None
        self._read_before: dict[bytes, dict] = {}
        self._watching = False
        self.plan: list[dict] = []  # pending clean-up, waiting for a yes
        old = self._settings()
        if {"password", "address", "host", "google"} & set(old):
            self._save({k: v for k, v in old.items() if k not in ("password", "address", "host", "google")})

    # ---- settings ----

    def _settings(self) -> dict:
        return json.loads(MAIL_FILE.read_text()) if MAIL_FILE.exists() else {}

    def _save(self, settings: dict) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        MAIL_FILE.write_text(json.dumps(settings, indent=2))
        os.chmod(MAIL_FILE, 0o600)

    def _set(self, **values) -> None:
        self._save({**self._settings(), **values})

    @property
    def connected(self) -> str:
        """The signed-in Gmail address, or ""."""
        return google_account.address() if google_account.has(google_account.MAIL) else ""

    @property
    def let_through(self) -> list[str]:
        return self._settings().get("let_through", [])

    def set_let_through(self, people: str) -> list[str]:
        people_list = [p.strip() for p in re.split(r"[,;\n]", people) if p.strip()]
        self._set(let_through=people_list)
        return people_list

    # ---- reading ----

    def _account(self, change: bool = False) -> imaplib.IMAP4_SSL:
        address = self.connected
        if not address:
            raise ToolError(f"Your email isn't connected yet. Open Dock's settings on the {self.hub.computer} and sign in with Google.")
        token = google_account.credentials().token
        box = imaplib.IMAP4_SSL(GMAIL_IMAP, timeout=15)
        try:
            box.authenticate("XOAUTH2", lambda _: f"user={address}\x01auth=Bearer {token}\x01\x01".encode())
        except imaplib.IMAP4.error:
            box.logout()
            raise ValueError("Gmail didn't accept Dock's sign-in. Sign in with Google again in Dock's settings.")
        # Read-only unless a clean-up was approved.
        status, _ = box.select(_quote(MAIL_FOLDER), readonly=not change)
        if status != "OK":
            box.logout()
            raise ToolError(f"I can't find the {MAIL_FOLDER} label in Gmail.")
        return box

    @staticmethod
    def _fetch(box, uids: list[bytes], part: str) -> dict[bytes, bytes]:
        """Fetch several emails in one round trip."""
        if not uids:
            return {}
        data = box.uid("FETCH", b",".join(uids), f"({part})")[1]
        found = {}
        for n, item in enumerate(data):
            head = item[0] if isinstance(item, tuple) else item
            if not isinstance(head, bytes):
                continue
            after = data[n + 1] if isinstance(item, tuple) and n + 1 < len(data) and isinstance(data[n + 1], bytes) else b""
            uid = re.search(rb"UID (\d+)", head) or re.search(rb"UID (\d+)", after)
            if uid:
                found[uid.group(1)] = item[1] if isinstance(item, tuple) else head
        return found

    def _read(self, box, uids: list[bytes], since: datetime | None) -> list[dict]:
        """Emails with these ids after `since`, newest first (cached by id)."""
        new = [uid for uid in uids if uid not in self._read_before]
        sizes = {uid: int(m.group(1)) if (m := re.search(rb"RFC822\.SIZE (\d+)", info)) else 0
                 for uid, info in self._fetch(box, new, "RFC822.SIZE").items()}
        small = [uid for uid in new if sizes.get(uid, 0) <= MAX_FULL_BYTES]
        raw = {**self._fetch(box, small, "BODY.PEEK[]"),
               **self._fetch(box, [uid for uid in new if uid not in small], "BODY.PEEK[HEADER]")}
        for uid, data in raw.items():
            message = email.message_from_bytes(data)
            when = email.utils.parsedate_to_datetime(message["Date"]) if message["Date"] else None
            name, address = email.utils.parseaddr(_decode(message["From"]))
            self._read_before[uid] = {
                "uid": uid.decode(), "id": _decode(message["Message-ID"]) or uid.decode(),
                "from": name or address, "address": address.lower(),
                "subject": _decode(message["Subject"]) or "(no subject)",
                "when": strftime(when.astimezone(), "%-I:%M %p") if when else "",
                "date": when.astimezone().isoformat(timespec="minutes") if when else "",
                "text": _text_of(message) if sizes.get(uid, 0) <= MAX_FULL_BYTES else "",
                "bulk": bool(message["List-Unsubscribe"] or message["List-Id"]),
                **_unsubscribe_info(message),
            }
        found = []
        for uid in reversed(uids):
            m = self._read_before.get(uid)
            if m and not (since and m["date"] and datetime.fromisoformat(m["date"]).replace(tzinfo=None) < since):
                found.append(dict(m))
        return found

    def unread_since(self, since: datetime, everything: bool = False) -> list[dict]:
        """Unread emails after `since`, newest first. everything: all emails in the label."""
        with self._account() as box:
            if everything:
                uids = box.uid("SEARCH", None, "ALL")[1][0].split()[-MAX_MESSAGES:]
                return self._read(box, uids, None)
            day = since.strftime("%d-%b-%Y")  # IMAP searches by day; the time is checked in _read
            uids = box.uid("SEARCH", None, "UNSEEN", "SINCE", day)[1][0].split()[-MAX_MESSAGES:]
            return self._read(box, uids, since)

    def unread_count(self, since: datetime) -> int:
        with self._account() as box:
            if DEMO:
                return len(box.uid("SEARCH", None, "ALL")[1][0].split())
            return len(box.uid("SEARCH", None, "UNSEEN", "SINCE", since.strftime("%d-%b-%Y"))[1][0].split())

    def for_search(self, days: int, limit: int, known: set[str]) -> tuple[list[str], list[dict]]:
        """Email ids from the last `days` days and full emails not in `known` (for search_my_stuff)."""
        with self._account() as box:
            day = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
            uids = box.uid("SEARCH", None, "SINCE", day)[1][0].split()[-limit:]
            new = [u for u in uids if u.decode() not in known]
            return [u.decode() for u in uids], self._read(box, new, None)

    def recent(self) -> list[dict]:
        """Newest emails from the last CLEANUP_DAYS days, for a clean-up."""
        with self._account() as box:
            day = (datetime.now() - timedelta(days=CLEANUP_DAYS)).strftime("%d-%b-%Y")
            uids = box.uid("SEARCH", None, "SINCE", day)[1][0].split()[-MAX_CLEANUP:]
            return self._read(box, uids, None)

    def _since(self, period: str) -> tuple[datetime, str]:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        session = self.focus.session
        if period == "auto" and session:
            return datetime.fromtimestamp(session["started"]), "since your focus session started"
        if period == "week":
            return today - timedelta(days=6), "this week"
        if period == "overnight":
            return today - timedelta(hours=6), "since last night"
        return today, "today"

    def sort(self, messages: list[dict]) -> list[dict]:
        """Classify emails (kind, gist, urgency, folder); results are cached."""
        new = [m for m in messages if m["id"] not in self._sorted]
        answers = dict(zip((m["id"] for m in new), self._sort_with_ai(new))) if new else {}
        for key, about in answers.items():
            if about.pop("answered"):
                self._sorted[key] = about
        return [{**m, **(self._sorted.get(m["id"]) or answers[m["id"]])} for m in messages]

    def _sort_with_ai(self, messages: list[dict]) -> list[dict]:
        lines = [f"[E{n}] From: {m['from']} <{m['address']}>{' (automatic sender)' if m['bulk'] else ''}"
                 f" | Subject: {m['subject']}" + (f" | {m['text']}" if m["text"] else "") for n, m in enumerate(messages, start=1)]
        now = strftime(datetime.now(), "Now: %A, %B %-d, %Y, %-I:%M %p")
        result = _json(bedrock.ask(now + "\n" + "\n".join(lines), SORT_SYSTEM, 300 + 70 * len(messages), bedrock.SMART_MODEL_ID,
                                     purpose="email sort"))
        about = {str(e.get("id", "")).upper(): e for e in result.get("emails", []) if isinstance(e, dict)}
        sorted_messages = []
        for n, m in enumerate(messages, start=1):
            e = about.get(f"E{n}", {})
            # Bills and security alerts come from automated senders too.
            kind = e.get("kind") if e.get("kind") in KINDS else ("update" if m["bulk"] else "important")
            sorted_messages.append({"answered": bool(e), "kind": kind, "urgent": bool(e.get("urgent")) and kind == "important",
                                    "gist": str(e.get("gist", ""))[:80], "folder": _folder_name(e.get("folder", "")),
                                    "todo": str(e.get("todo") or "")[:90] if kind == "important" else "",
                                    "due": _due(e.get("due")) if kind == "important" and e.get("todo") else None})
        return sorted_messages

    def is_let_through(self, message: dict) -> bool:
        return any(person.lower() in (message["address"], message["from"].lower()) or
                   (len(person) > 2 and person.lower() in message["from"].lower()) for person in self.let_through)

    # ---- "What did I miss?" ----

    async def new_mail(self, period: str = "auto", everything: bool = False) -> dict:
        """New email, sorted: {"said", "important", "counts", "rest", "spoken"}."""
        since, said = self._since(period)
        began = time.monotonic()
        try:
            messages = await asyncio.to_thread(self.unread_since, since, everything)
        except ValueError as e:
            raise ToolError(str(e))
        except (OSError, imaplib.IMAP4.error) as e:
            raise ToolError(f"I couldn't reach your email right now ({str(e)[:60]}).")
        fetched = time.monotonic()
        messages = await asyncio.to_thread(self.sort, messages) if messages else []
        if time.monotonic() - began > 4:
            print(f"Email was slow: Gmail {fetched - began:.1f}s, sorting {time.monotonic() - fetched:.1f}s")
        important = sorted((m for m in messages if m["kind"] == "important"), key=lambda m: not m["urgent"])
        counts = {k: sum(1 for m in messages if m["kind"] == k) for k in ("update", "promotion", "spam")}
        rest = _counted(counts)
        lines = [f"{m['from']}: {m['gist'] or m['subject']}." for m in important[:SPOKEN_IMPORTANT]]
        if len(important) > SPOKEN_IMPORTANT:
            lines.append(f"And {len(important) - SPOKEN_IMPORTANT} more on your screen.")
        # Only count updates and promotions, unless nothing important came in.
        if not messages:
            spoken = f"No new email {said}."
        elif lines:
            spoken = " ".join(lines)
        else:
            spoken = f"Nothing important {said}." + (f" Just {rest}." if rest else "")
        # Offer to-dos from important emails (deadlines first, skip ones already listed).
        listed = await asyncio.to_thread(lambda: [m["todo"] for m in important if m["todo"] and self.notes.is_listed(m["todo"])])
        todos = [{"text": m["todo"], "due": m["due"]} for m in important if m["todo"] and m["todo"] not in listed]
        self.offered_todos = sorted(todos, key=lambda t: (t["due"] is None, t["due"][0] if t["due"] else datetime.max))[:3]
        offer = ""
        if self.offered_todos:
            first = self.offered_todos[0]
            text = first["text"][0].lower() + first["text"][1:] if first["text"][:2].istitle() else first["text"]
            offer = (f"Want a calendar reminder to {text}, due {_when(first['due'])}?" if self._to_calendar(first)
                     else f"Want me to add a to-do to {text}?")
        return {"said": said, "important": important, "counts": counts, "rest": rest, "spoken": spoken, "offer": offer}

    def _to_calendar(self, todo: dict) -> bool:
        """Deadlines go on the calendar when Dock can add events."""
        return bool(todo.get("due")) and bool(self.calendar and self.calendar.can_add)

    def card_items(self, important: list[dict]) -> list[dict]:
        items = []
        for m in important[:10]:
            todo = {"text": m["todo"], "due": m["due"]}
            items.append({"from": m["from"], "gist": m["gist"] or m["subject"], "when": m["when"], "urgent": m["urgent"],
                          "todo": m["todo"], "todo_where": "calendar" if m["todo"] and self._to_calendar(todo) else "list",
                          "todo_when": _when(m["due"]) if m["due"] else ""})
        return items

    async def summary(self, period: str = "auto") -> str:
        """Summarize new email and show the list on the phone."""
        found = await self.new_mail(period)
        important, counts, rest, said = found["important"], found["counts"], found["rest"], found["said"]
        if important or rest:
            await self.hub.push_phone(
                "mail", title=(f"{len(important)} important email{'s' if len(important) != 1 else ''} {said}" if important
                               else f"Nothing important {said}"),
                items=self.card_items(important),
                rest=(f"Also {rest}." + (" Say “clean up my inbox” to clear them." if counts["promotion"] + counts["spam"] else "")) if rest else "")
        return f"{found['spoken']} {found['offer']}".strip()

    async def add_todo(self, text: str = "") -> str:
        """Add an offered to-do to the list (and calendar, if it has a deadline)."""
        todo = next((t for t in self.offered_todos if t["text"] == text), None) if text else None
        todo = todo or (self.offered_todos[0] if self.offered_todos and not text else {"text": text, "due": None})
        if not todo["text"]:
            raise ToolError("There's no to-do from your email to add right now.")
        self.offered_todos = [t for t in self.offered_todos if t is not todo]
        note = await self.notes.add(todo["text"], todo["due"], deadline=True)
        await self.hub.push_phone("done", title=(f"On your calendar: {note['text']}" if note.get("on_calendar") else f"Added: {note['text']}")[:48])
        said = self.notes.confirm(note)
        if todo["due"] and not note.get("on_calendar") and not (self.calendar and self.calendar.can_add):
            said += " Sign in with Google in Dock's settings and allow Calendar, and I can put these on your calendar too."
        return said

    # ---- clean-up (always asks first) ----

    async def propose_cleanup(self) -> str:
        try:
            messages = await asyncio.to_thread(self.recent)
        except ValueError as e:
            raise ToolError(str(e))
        if not messages:
            return "Your inbox has nothing from the last month to clean up."
        messages = await asyncio.to_thread(self.sort, messages)
        self.plan = [{**m, "to": "Trash" if m["kind"] in ("spam", "promotion") else m["folder"]}
                     for m in messages if m["kind"] in ("spam", "promotion", "update")]
        if not self.plan:
            return "Your inbox looks clean: everything there seems important."
        await self.hub.push_phone("mail_plan", items=[{"from": m["from"], "subject": m["gist"] or m["subject"], "to": m["to"],
                                                       "kind": m["kind"], "can_unsubscribe": self._can_unsubscribe(m)}
                                                      for m in self.plan])
        count = len(self.plan)
        return (f"I have {count} suggestion{'s' if count != 1 else ''} to clean up your inbox. "
                "Check the list, then tap Clean up or say yes.")

    def _special(self, box, flag: str) -> str | None:
        """Folder with a special-use flag, e.g. \\Trash -> "[Gmail]/Trash"."""
        for line in box.list()[1]:
            match = re.match(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)', line or b"")
            if match and flag.encode().lower() in match["flags"].lower():
                return match["name"].decode().strip('"')
        return None

    def _do_cleanup(self, picked: list[dict]) -> dict:
        moved: dict[str, int] = {}
        with self._account(change=True) as box:
            can_move = "MOVE" in box.capabilities
            groups: dict[str, list[str]] = {}
            for m in picked:
                groups.setdefault(m["to"], []).append(m["uid"])
            for to, uids in groups.items():
                folder = (self._special(box, "\\Trash") or "Trash") if to == "Trash" else to
                if to != "Trash" or folder == "Trash":
                    box.create(_quote(folder))
                uid_set = ",".join(uids)
                if can_move:
                    box.uid("MOVE", uid_set, _quote(folder))
                else:  # older servers: copy, then mark deleted
                    box.uid("COPY", uid_set, _quote(folder))
                    box.uid("STORE", uid_set, "+FLAGS", "(\\Deleted)")
                    box.expunge()
                moved[to] = moved.get(to, 0) + len(uids)
        return moved

    async def clean_up(self, numbers: list[int] | None = None) -> str:
        """Apply the proposed clean-up (all, or only the ticked items)."""
        if not self.plan:
            raise ToolError("I haven't suggested a clean-up yet. Say clean up my inbox first.")
        picked = self.plan if numbers is None else [self.plan[n] for n in numbers if 0 <= n < len(self.plan)]
        self.plan = []
        await self.hub.push_phone("mail_plan_done")
        if not picked:
            return "Okay, I left your inbox as it is."
        try:
            moved = await asyncio.to_thread(self._do_cleanup, picked)
        except (OSError, imaplib.IMAP4.error) as e:
            raise ToolError(f"Your email didn't let me move them ({str(e)[:60]}).")
        trashed = moved.pop("Trash", 0)
        filed = sum(moved.values())
        await self.hub.push_phone("done", title=f"Cleaned up {trashed + filed} emails")
        parts = ([f"{trashed} to the Trash"] if trashed else []) + ([f"{filed} filed into {', '.join(moved)}"] if filed else [])
        return f"Done: {' and '.join(parts)}." + (" The Trash keeps them for a while if you need one back." if trashed else "")

    # ---- unsubscribe (promotions only) ----

    @staticmethod
    def _can_unsubscribe(m: dict) -> bool:
        return m.get("kind") != "spam" and bool(m.get("unsubscribe_url"))

    async def unsubscribe(self, m: dict) -> str:
        """One-click unsubscribe if supported, else open the sender's page."""
        if m.get("kind") == "spam":
            return f"That one looks like spam. Unsubscribing would tell them your address works, so I'll leave it."
        url = m.get("unsubscribe_url", "")
        if not url:
            return f"{m['from']} doesn't offer a way to unsubscribe that Dock can use (only by sending an email)."
        if m.get("one_click"):
            request = urllib.request.Request(url, data=b"List-Unsubscribe=One-Click", method="POST",
                                             headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Dock"})
            try:
                await asyncio.to_thread(lambda: urllib.request.urlopen(request, timeout=15).read(0))
                await self.hub.push_phone("done", title=f"Unsubscribed from {m['from']}"[:48])
                return f"Done: unsubscribed from {m['from']}."
            except Exception as e:
                print(f"One-click unsubscribe failed for {m['from']}: {e!r}")
        try:
            await self.hub.ask_agent("open_url", url=url)
        except (AgentOffline, AgentError) as e:
            raise ToolError(f"I couldn't open {m['from']}'s unsubscribe page ({e}).")
        return f"I opened {m['from']}'s unsubscribe page on your {self.hub.computer}. Confirm there."

    def find_sender(self, sender: str) -> dict | None:
        """Newest recent email from a sender (by name or address)."""
        wanted = sender.lower().strip()
        matches = [m for m in self.recent() if wanted in m["from"].lower() or wanted in m["address"]]
        return next((m for m in matches if m["unsubscribe_url"]), matches[0] if matches else None)

    def voice_context(self) -> str:
        text = ""
        if self.plan:
            text += (f" Dock just proposed an email clean-up ({len(self.plan)} emails): \"yes\", \"do it\" or "
                     "\"clean it up\" means clean_up_email with confirm true, never do_app_action.")
        if self.offered_todos:
            text += (" Dock offered to add these to-dos from email: " + "; ".join(f"'{t['text']}'" for t in self.offered_todos)
                     + ". \"Yes\", \"add it\" or \"put it on my calendar\" means add_email_todo (with that text if they "
                     "say which), never notes.")
        return text

    async def from_phone(self, message: dict) -> None:
        kind = message.get("kind")
        if kind == "mail_todo":
            await self.add_todo(str(message.get("text", "")))
        elif kind == "mail_unsubscribe":
            n = message.get("n")
            if isinstance(n, int) and 0 <= n < len(self.plan):
                await self.hub.push_phone("toast", text=await self.unsubscribe(self.plan[n]))
        elif kind == "mail_cleanup":
            try:
                spoken = await self.clean_up([int(n) for n in message.get("items", []) if str(n).isdigit()])
            except ToolError as e:
                spoken = str(e)
            await self.hub.push_phone("toast", text=spoken)
        elif kind == "mail_cleanup_cancel":
            self.plan = []
            await self.hub.push_phone("mail_plan_done")

    # ---- focus: hold mail, let important mail through ----

    def ensure_watch(self) -> None:
        if not self._watching:
            self._watching = True
            asyncio.get_running_loop().create_task(self._watch())
            if DEMO and self.connected:
                asyncio.get_running_loop().create_task(self._sort_demo_emails())

    async def _sort_demo_emails(self) -> None:
        """With a test label, sort its emails once at startup."""
        try:
            self.demo_read = await self.new_mail("today", everything=True)
            print("Demo emails sorted")
        except Exception as e:
            print(f"Couldn't sort the demo emails yet: {e!r}")

    async def _watch(self) -> None:
        session_id = None
        while True:
            await asyncio.sleep(CHECK_SECONDS)
            s = self.focus.session
            if not self.connected or not s or s["state"] not in ("running", "away", "paused"):
                continue
            if s["started"] != session_id:
                session_id, self._seen_in_focus = s["started"], set()
            try:
                messages = await asyncio.to_thread(self.unread_since, datetime.fromtimestamp(s["started"]))
            except Exception as e:
                print(f"Mail check failed: {e!r}")
                continue
            for m in messages:
                if m["id"] in self._seen_in_focus:
                    continue
                self._seen_in_focus.add(m["id"])
                why = ""
                if self.is_let_through(m):
                    why = "On your let-through list"
                elif not m["bulk"]:
                    verdict = _json(await asyncio.to_thread(
                        bedrock.ask, f"From: {m['from']}\nSubject: {m['subject']}\n{m['text']}", URGENT_SYSTEM, 60, purpose="email urgency"))
                    why = f"Looks urgent: {verdict.get('why', '')}".strip(": ") if verdict.get("urgent") else ""
                if why:
                    print(f"Mail let through during focus: {m['from']} ({why})")
                    await self.hub.push_phone("tip", title=f"Email from {m['from']}", detail=f"{m['subject']}\n{why}", sound=True)

    def held_count(self) -> int:
        return len(self._seen_in_focus)

    # ---- tools ----

    def register(self, mcp: MCPServer) -> None:
        @mcp.tool()
        async def check_email(period: Literal["auto", "today", "week"] = "auto") -> str:
            """What's new in the user's email: "what did I miss?", "any new email?",
            "anything important in my inbox?". Sums up only the important unread
            email (real people, deadlines, bills, school, work), most urgent first,
            and counts the rest (updates, promotions, spam); the list is on the
            phone. period "auto": since their last focus session started (or today
            if there was none)."""
            return await self.summary(period)

        @mcp.tool()
        async def clean_up_email(confirm: bool = False) -> str:
            """Tidy the user's inbox: "clean up my inbox", "delete the spam", "get
            rid of promotions", "organize my email". With confirm false (always
            first) it only proposes: spam and promotions to the Trash, updates like
            receipts filed into folders, shown as a checklist on the phone; nothing
            changes. Call it with confirm true only when the user then says yes."""
            if confirm:
                return await self.clean_up()
            return await self.propose_cleanup()

        @mcp.tool()
        async def add_email_todo(text: str = "") -> str:
            """Add a to-do that Dock just offered from an email ("yes, add it", "put
            it on my calendar"): on the calendar at its deadline, or on the list.
            text: which one, if Dock offered several; empty means the first."""
            return await self.add_todo(text)

        @mcp.tool()
        async def unsubscribe_email(sender: str) -> str:
            """Unsubscribe the user from a sender's emails: "unsubscribe from Old
            Navy", "stop these DoorDash emails". Uses the sender's one-click
            unsubscribe, or opens their unsubscribe page on the Mac."""
            try:
                found = await asyncio.to_thread(self.find_sender, sender)
            except ValueError as e:
                raise ToolError(str(e))
            if found is None:
                raise ToolError(f"I didn't find any email from {sender} in the last month.")
            return await self.unsubscribe(found)
