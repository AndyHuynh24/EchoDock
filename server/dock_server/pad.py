"""Phone shortcut pad: up to 9 buttons for the app in front on the computer.

Bedrock picks useful menu commands once per app (cached in .data/); items the user
asked about come first. Tapping a button clicks that menu item.
"""

import asyncio
import json
import re
import time

from dock_server import bedrock
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.menu_words import display_name, is_risky
from dock_server.savings import Savings
from dock_server.state import DATA_DIR, State

PAD_SIZE = 9
CHOICES_FILE = DATA_DIR / "pad_choices_v2.json"
SUGGESTIONS_FILE = DATA_DIR / "app_suggestions.json"
READING_APPS = {"Safari", "Google Chrome", "Arc", "Firefox", "Microsoft Edge", "Preview", "Adobe Acrobat Reader",
                "Microsoft Word", "Pages", "TextEdit", "Mail", "Notes", "Books"}
SKIP_MENUS = {"History", "Bookmarks", "Favorites", "Window", "Help"}
NEW_DOWNLOAD_SECONDS = 30 * 60

SUGGEST_SYSTEM = (
    "You suggest what someone using a Mac app every day (a student or a professional) would really "
    "want to ask a voice assistant about it. From the app's menu items, pick the 4 that save real time "
    "or fix a common annoyance, and that people often don't know or forget. Good examples: Safari "
    "\"Reopen the tab I just closed\", \"Read this page without clutter\"; Preview \"Sign this PDF\", "
    "\"Combine these PDFs into one\"; iMovie \"Pull the audio off this clip\"; VS Code \"Turn on zen "
    "mode\"; RStudio \"Restart R and clear everything\". Never pick: basics everyone knows (new tab, "
    "open, save, print, undo, copy, paste, find, quit), showing or hiding toolbars, sidebars or bars, "
    "developer or debugging tools, page source, settings, or anything that deletes or clears data. "
    "Write each as a short natural request (under 40 characters) about what the user wants done, "
    "not the menu name.\n"
    'Reply with only JSON: [{"item": <number>, "ask": "..."}]'
)

PICK_SYSTEM = (
    "You choose the most useful everyday commands of a Mac app for a touch shortcut pad. "
    "Prefer actions people repeat while working that are worth a button (like split clip, run, "
    "export, add a chart, insert a comment). "
    "Never pick basics everyone already knows the keys for (new, open, close, save, print, undo, "
    "redo, cut, copy, paste, select all, find). Avoid settings, help, window management, quitting "
    "and deleting. "
    "Reply with only the item numbers, separated by commas, most useful first."
)


def _key(path: list[str]) -> str:
    return " > ".join(path)


def _title(path: list[str]) -> str:
    """Button label, including its submenu."""
    name, parent = display_name(path[-1]), display_name(path[-2]) if len(path) > 2 else ""
    return f"{parent} › {name}" if parent and parent.lower() != name.lower() else name


# Basics that are never suggested.
BASICS = re.compile(r"^(new|open|close|save|print|undo|redo|cut|copy|paste|select all|find|quit|"
                    r"minimi[sz]e|zoom|preferences|settings|help|new tab|new window)\b", re.IGNORECASE)


def _parse_suggestions(answer: str, candidates: list[dict]) -> list[str]:
    match = re.search(r"\[.*\]", answer, re.DOTALL)
    try:
        picked = json.loads(match.group()) if match else []
    except json.JSONDecodeError:
        return []
    asks = []
    for entry in picked if isinstance(picked, list) else []:
        if not isinstance(entry, dict):
            continue
        number, ask = entry.get("item"), str(entry.get("ask", "")).strip()
        if not (isinstance(number, int) and 1 <= number <= len(candidates) and 0 < len(ask) <= 60):
            continue
        if BASICS.match(display_name(candidates[number - 1]["path"][-1])):
            continue
        asks.append(ask[0].upper() + ask[1:])
    return asks[:4]


class Pad:
    def __init__(self, hub: Hub, state: State, savings: Savings):
        self.hub = hub
        self.state = state
        self.savings = savings
        self.downloads = None
        self.choices: dict[str, list[str]] = json.loads(CHOICES_FILE.read_text()) if CHOICES_FILE.exists() else {}
        self.suggestions: dict[str, list[str]] = json.loads(SUGGESTIONS_FILE.read_text()) if SUGGESTIONS_FILE.exists() else {}

    def _pick(self, app: str, items: list[dict]) -> list[str]:
        candidates = [i for i in items if not is_risky(i["path"][-1]) and not BASICS.match(display_name(i["path"][-1]))]
        lines = [
            f"{n}. {_key(i['path'])}" + (f" ({i['shortcut']})" if i["shortcut"] else "")
            for n, i in enumerate(candidates, start=1)
        ]
        answer = bedrock.ask(f"App: {app}\n\nMenu items:\n" + "\n".join(lines), PICK_SYSTEM, max_tokens=60, purpose="pad buttons")
        numbers = [int(n) for n in re.findall(r"\d+", answer) if 1 <= int(n) <= len(candidates)]
        return [_key(candidates[n - 1]["path"]) for n in numbers][:PAD_SIZE]

    def _suggest_for_app(self, app: str, items: list[dict]) -> list[str]:
        """Things worth asking about this app (one model call per app)."""
        candidates = [i for i in items if not is_risky(i["path"][-1]) and i["path"][0] not in SKIP_MENUS][:500]
        lines = [f"{n}. {_key(i['path'])}" for n, i in enumerate(candidates, start=1)]
        try:
            answer = bedrock.ask(f"App: {app}\n\nMenu items:\n" + "\n".join(lines), SUGGEST_SYSTEM, 300,
                                 bedrock.SMART_MODEL_ID, purpose="app suggestions")
        except Exception as e:
            print(f"Couldn't pick suggestions for {app}: {e!r}")
            return []
        return _parse_suggestions(answer, candidates)

    def examples(self, app: str, buttons: list[dict]) -> list[str]:
        """Suggestions for right now: context first, then the app's own."""
        now = []
        new = self.downloads.last_download if self.downloads else {}
        if new and time.time() - new.get("at", 0) < NEW_DOWNLOAD_SECONDS and new["file"] not in self.state.new_downloads:
            now.append(f"Where should {new['file']} go?")
        if app in READING_APPS:
            now.append("Summarize this")
        if time.localtime().tm_hour >= 16:
            now.append("What did I work on today?")
        tips = list(dict.fromkeys(now[:2] + self.suggestions.get(app, []) + now[2:]))
        return tips[:6] or ["Tidy my downloads", "What's on today?"]

    async def front_app_changed(self, event: dict) -> None:
        app, pid, items = event["app"], event["pid"], event.get("items") or []
        if not items:
            return
        if app not in self.choices:
            self.choices[app] = await asyncio.to_thread(self._pick, app, items)
            DATA_DIR.mkdir(exist_ok=True)
            CHOICES_FILE.write_text(json.dumps(self.choices, indent=2))
        if app not in self.suggestions:
            self.suggestions[app] = await asyncio.to_thread(self._suggest_for_app, app, items)
            if self.suggestions[app]:
                DATA_DIR.mkdir(exist_ok=True)
                SUGGESTIONS_FILE.write_text(json.dumps(self.suggestions, indent=2))

        # Items the user asked about come first.
        asked = sorted(
            ((count, _key(list(path))) for (asked_app, path), count in self.state.times_asked.items() if asked_app == app),
            reverse=True,
        )
        order = list(dict.fromkeys([key for _, key in asked] + self.choices[app]))
        by_key = {_key(i["path"]): i for i in items}
        buttons = [
            {"title": _title(by_key[k]["path"]), "shortcut": by_key[k]["shortcut"], "path": by_key[k]["path"]}
            for k in order
            if k in by_key and not is_risky(by_key[k]["path"][-1]) and not BASICS.match(display_name(by_key[k]["path"][-1]))
        ][:PAD_SIZE]
        tries = self.examples(app, buttons)

        self.state.pad.clear()
        self.state.pad.update(kind="pad", app=app, pid=pid, buttons=buttons, examples=tries)
        await self.hub.push_phone("pad", app=app, pid=pid, buttons=buttons, examples=tries)

    async def phone_connected(self, ws) -> None:
        if self.state.pad:
            await ws.send_text(json.dumps(self.state.pad))

    async def press(self, message: dict) -> None:
        path = message.get("path") or []
        if not self.state.pad or not path:
            return
        name = display_name(path[-1])
        if is_risky(name):
            await self.hub.push_phone("card", title=f"Dock won't click {name}", detail="Please click it yourself.")
            return
        try:
            await self.hub.ask_agent("press_menu", pid=self.state.pad["pid"], path=path)
            await self.hub.push_phone("toast", text=f"✓ {name}")
            await self.savings.add("clicked")
        except AgentOffline:
            await self.hub.push_phone("card", title="Your computer isn't connected", detail="Start the Dock desktop agent.")
        except AgentError as e:
            await self.hub.push_phone("card", title=f"Couldn't do {name}", detail=str(e))
