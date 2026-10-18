"""Suggest where a file belongs: right after it downloads, or while you're
choosing where to save it.

- New downloads: the desktop agent notices each finished download (see the
  agent's tidy.py) and sends its name, the website it came from and the
  user's folders. The phone shows "Put it in Documents/school/stat310? Move /
  Not now". Nothing moves until the user taps Move or says "yes, move it".
- Save windows: when a Save window opens on the Mac (see the agent's
  savepanel.py), the phone shows "Save it in stat310/homework? Save here / Not
  now", and an arrow next to the Save window shows the same. "Save here" (or
  "save it there") switches the Save window to that folder and clicks Save.

Both ask the AI for the most likely folder, using where the user put similar
files before. Files Dock isn't fairly sure about get no suggestion, so there
are no wrong nudges.

Automatic suggestions are OFF by default, because each one is an AI call
(about $0.001). The user turns them on with the switch on the phone or by
voice ("turn on folder suggestions"); the choice is kept in
.data/settings.json. With them off:
- a Save window makes the phone ask first: "Want Dock to suggest a folder?"
  Yes / No. The question goes away by itself when the Save window closes, the
  user picks a folder in it, switches to another app, or asks Dock for
  something else.
- "where should this go?" still suggests a folder for the open Save window or
  the newest download, once.
"""

import asyncio
import json
import re
import time

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import bedrock
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.savings import Savings
from dock_server.state import DATA_DIR, State
from dock_server.tools import tidy

SETTINGS_FILE = DATA_DIR / "settings.json"
UNDO_MOVE_SECONDS = 300  # "undo" this soon after a move means "put the files back"

SUGGEST_SYSTEM = (
    "A student is putting a file on their Mac (it just downloaded, or they are choosing "
    "where to save it). Pick the existing folder it "
    "most likely belongs in, using what the file says (its start, when given: the course, "
    "project or topic it is really about matters more than a vague name like \"Untitled\" "
    "or \"document\"), the file name, the website it came from, the folder names, the "
    "window it's saved from, and where the user put similar files before (follow their "
    "habits). Watch "
    "numbers: an HW4 file doesn't belong in an HW2 folder; use the course folder instead. "
    "If a new folder inside an existing one would clearly help, you may suggest it with "
    "new_folder true. If you are not fairly sure, reply with an empty \"to\".\n"
    "Reply with only JSON: "
    '{"to": "folder path from the list", "new_folder": false, "why": "few words"}'
)


def _parse(answer: str, file: str, folders: set[str]) -> dict | None:
    match = re.search(r"\{.*\}", answer, re.DOTALL)
    try:
        reply = json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        return None
    to = str(reply.get("to", "")).strip().strip("/")
    new_folder = bool(reply.get("new_folder")) and to not in folders
    if not to or (to not in folders and not (new_folder and to.rsplit("/", 1)[0] in folders)):
        return None
    return {"file": file, "to": to, "new_folder": new_folder, "why": str(reply.get("why", ""))}


CONTENT_CHARS = 800  # how much of what the file says the AI sees


async def _suggest(file: str, about: str, folders: list[str], content: str = "") -> dict | None:
    """Ask the AI where `file` belongs. `about` says where it comes from; `content`
    is the start of what it says, if Dock could read it."""
    if not folders:
        return None
    past = "\n".join(f"- {m['file']} → {m['to']}" for m in tidy.past_moves()) or "(none yet)"
    says = " ".join(content.split())[:CONTENT_CHARS]
    prompt = (f"File: {file} ({about})\n" + (f"What it says (start): {says}\n" if says else "")
              + f"\nWhere the user put earlier files:\n{past}"
              "\n\nThe user's folders:\n" + "\n".join(folders))
    try:
        answer = await asyncio.to_thread(bedrock.ask, prompt, SUGGEST_SYSTEM, 150)
    except Exception as e:
        print(f"Couldn't suggest a folder for {file}: {e!r}")
        return None
    suggestion = _parse(answer, file, set(folders))
    print(f"Folder for {file!r} ({about}): {suggestion['to'] if suggestion else 'not sure'}")
    return suggestion


class NewDownloads:
    def __init__(self, hub: Hub, state: State, savings: Savings):
        self.hub = hub
        self.state = state
        self.savings = savings
        self.open_save_panel = ""  # file name in the Save window open on the Mac
        self.save_panel_files: dict[str, float] = {}  # file -> when Dock made a Save-window suggestion
        self.save_panel_event: dict = {}  # the Save window open on the Mac, as the agent described it
        # For that Save window, when suggestions are off: "" (not asked yet), "asked"
        # (the phone is asking), "yes" (suggest, also after a rename) or "no".
        self.save_choice = ""
        self.last_download: dict = {}     # the newest finished download, as the agent described it
        settings = json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {}
        self.automatic = bool(settings.get("folder_suggestions", False))

    async def set_automatic(self, on: bool) -> None:
        """Turn automatic folder suggestions on or off, and tell the phones."""
        self.automatic = on
        settings = json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {}
        settings["folder_suggestions"] = on
        DATA_DIR.mkdir(exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
        await self.hub.push_phone("settings", folder_suggestions=on)
        if on and self.save_choice == "asked":
            await self.answer_save_ask(True)  # turning them on answers the question too

    async def on_new(self, event: dict) -> None:
        """The agent says a download just finished."""
        self.last_download = {**event, "at": time.time()}
        if self.automatic and time.time() - self.save_panel_files.get(event["file"], 0) >= 300:
            # (If Dock already suggested a folder in the Save window, don't ask twice.)
            await self._suggest_download(event)

    async def _suggest_download(self, event: dict) -> dict | None:
        file = event["file"]
        about = "just downloaded" + (f" from {event['came_from']}" if event.get("came_from") else "")
        content = await self._ask_text("file_start", path=event["path"]) if event.get("path") else ""
        suggestion = await _suggest(file, about, event.get("folders", []), content)
        if suggestion:
            self.state.new_downloads[file] = suggestion
            await self.hub.push_phone("download", **suggestion)
        return suggestion

    async def on_save_panel(self, event: dict) -> None:
        """A Save window opened on the Mac (or its file name changed)."""
        self.open_save_panel = event["file"]
        self.save_panel_event = event
        if self.automatic or self.save_choice == "yes":
            await self._suggest_save(event)
        elif self.save_choice in ("", "asked"):
            # Suggestions are off: ask first, since each suggestion uses a little AI.
            self.save_choice = "asked"
            await self.hub.push_phone("save_ask", file=event["file"], app=event.get("app", ""))

    async def answer_save_ask(self, yes: bool) -> None:
        """The user answered "Want Dock to suggest a folder?" for the open Save window."""
        if self.save_choice != "asked":
            return
        self.save_choice = "yes" if yes else "no"
        await self.hub.push_phone("save_ask_done")
        if yes and not await self._suggest_save(self.save_panel_event) and self.open_save_panel:
            await self.hub.push_phone("card", title="Not sure",
                                      detail=f"I'm not sure where {self.open_save_panel} belongs. Pick a folder in the Save window.")

    async def skip_save_ask(self, why: str) -> None:
        """Something else happened, so the question no longer fits: drop it."""
        if self.save_choice == "asked":
            print(f"Skipped the save question: {why}")
            self.save_choice = "no"
            await self.hub.push_phone("save_ask_done")

    async def on_save_panel_left(self, event: dict) -> None:
        await self.skip_save_ask("switched to another app")

    async def on_save_panel_folder_changed(self, event: dict) -> None:
        await self.skip_save_ask("picked a folder in the Save window")

    async def _suggest_save(self, event: dict) -> dict | None:
        file, app = event["file"], event.get("app", "")
        about = f"being saved from {app}" + (f", window \"{event['window_title']}\"" if event.get("window_title") else "")
        content = await self._ask_text("save_panel_text")
        suggestion = await _suggest(file, about, event.get("folders", []), content)
        if self.open_save_panel != file:
            return None  # the user already renamed the file or finished with the Save window
        if not suggestion:
            await self._clear_save_suggestion()  # an older suggestion (before a rename) no longer fits
            return None
        suggestion["app"] = app
        self.state.save_suggestion = suggestion
        self.save_panel_files[file] = time.time()
        await self.hub.push_phone("save_panel", **suggestion)
        try:
            folder = " › ".join(suggestion["to"].split("/")[-2:])
            await self.hub.ask_agent("point_at_save_folder", label=f"Dock suggests {folder}")
        except (AgentOffline, AgentError):
            pass
        return suggestion

    async def _ask_text(self, action: str, **args) -> str:
        """What the file says, from the Mac (only read when a suggestion is being made)."""
        try:
            return (await self.hub.ask_agent(action, timeout=6, **args)).get("text", "")
        except (AgentOffline, AgentError):
            return ""

    async def on_save_panel_closed(self, event: dict) -> None:
        await self.skip_save_ask("the Save window closed")
        self.open_save_panel = ""
        self.save_panel_event = {}
        self.save_choice = ""
        await self._clear_save_suggestion()

    async def _clear_save_suggestion(self) -> None:
        if self.state.save_suggestion:
            self.state.save_suggestion = {}
            await self.hub.push_phone("save_panel_done")

    async def save_here(self, folder: str = "", new_folder: bool = False) -> dict:
        """Switch the open Save window to `folder` (default: Dock's suggestion) and save."""
        if not folder:
            if not self.state.save_suggestion:
                raise AgentError("There's no Save window waiting for a folder.")
            folder, new_folder = self.state.save_suggestion["to"], self.state.save_suggestion["new_folder"]
        result = await self.hub.ask_agent("save_in_folder", timeout=15, folder=folder, new_folder=new_folder)
        self.state.save_suggestion = {}
        await self.hub.push_phone("save_panel_done")
        tidy.remember_moves([{"file": result["file"], "to": result["to"]}])
        await self.savings.add("save_folder")
        await self.hub.push_phone("card", title="Saved", detail=f"{result['file']} → {result['to']}")
        return result

    def register(self, mcp: MCPServer) -> None:
        """The MCP tools for putting files where they belong (one file, a Save
        window, or the whole Downloads folder)."""

        @mcp.tool()
        async def suggest_folders(all_downloads: bool = False) -> str:
            """Suggest where files belong, from the user's own folders and habits.
            Nothing is moved.
            - Default: the one file at hand: the Save window open on the Mac, or else
              the newest download ("where should this go?", "where should I save this?").
            - all_downloads: look through the whole Downloads folder and suggest a
              folder for each file, plus questions about unclear ones ("help me tidy
              my downloads"). Tell the user the suggestions briefly (how many, a
              couple of examples) and ask the questions; move only after they agree.
            The suggestions also appear on the phone, with buttons to accept them."""
            if all_downloads:
                return await tidy.plan(self.hub, self.state)
            if self.save_panel_event:
                if self.save_choice == "asked":  # asking counts as yes to the phone's question
                    self.save_choice = "yes"
                    await self.hub.push_phone("save_ask_done")
                suggestion = await self._suggest_save(self.save_panel_event)
                if suggestion:
                    return (f"I'd save {suggestion['file']} in {suggestion['to']}. Say save it there, "
                            "or tap Save here on the phone.")
                return f"I'm not sure where {self.save_panel_event['file']} belongs. Pick a folder in the Save window."
            if self.last_download:
                suggestion = await self._suggest_download(self.last_download)
                if suggestion:
                    return (f"I'd put {suggestion['file']} in {suggestion['to']}. Say move it, "
                            "or tap Move on the phone.")
                return f"I'm not sure where {self.last_download['file']} belongs."
            return "There's no Save window open and no new download yet. Say tidy my downloads to sort the older ones."

        @mcp.tool()
        async def put_in_folder(moves: list[tidy.Move] | None = None, folder: str = "", new_folder: bool = False) -> str:
            """Put files where they belong, only after the user agreed:
            - A Save window is open on the Mac: switch it to folder and click Save.
              Leave folder empty for the folder Dock suggested ("save it there",
              "yes, save it"), or name one ("save it on my Desktop").
            - Files in Downloads: pass moves, each with the exact file name and a
              folder path like "Documents/school/stat310" ("yes, move them" to the
              tidy suggestions, "put hw4.pdf on my Desktop"). For the new download
              Dock suggested a folder for, moves can stay empty: "yes, move it"
              uses Dock's folder, and "put it in Desktop instead" passes folder.
            Set new_folder (or a move's new_folder) to true only if the user agreed
            to create that folder."""
            folder = folder.strip().strip("/")
            try:
                if moves:
                    return tidy._moved_text(await tidy.move(self.hub, self.state, self.savings, [m.model_dump() for m in moves]))
                if self.save_panel_event or self.state.save_suggestion:
                    result = await self.save_here(folder, new_folder)
                    return f"Saved {result['file']} in {result['to'].rsplit('/', 1)[-1]}."
                if self.state.new_downloads:
                    waiting = self.state.new_downloads.values()
                    pending = [dict(w, to=folder, new_folder=new_folder) if folder else w for w in waiting]
                    return tidy._moved_text(await tidy.move(self.hub, self.state, self.savings, pending))
            except AgentOffline:
                raise ToolError("Your computer isn't connected to Dock right now.")
            except AgentError as e:
                raise ToolError(str(e))
            raise ToolError("Which file, and which folder? There's no Save window open and no download waiting.")

        @mcp.tool()
        async def undo_last_action() -> str:
            """Put back the files Dock moved most recently. Only right after Dock moved
            or tidied files ("put them back", "undo that move"). A plain "undo" in an
            app is the app's own Undo: use app_help for that."""
            return await tidy.undo(self.hub)

        @mcp.tool()
        async def set_folder_suggestions(on: bool) -> str:
            """Turn automatic folder suggestions on or off. When on, Dock suggests a
            folder by itself for every new download and every Save window (each one
            uses a little AI). When off (the default), it only suggests when asked."""
            await self.set_automatic(on)
            return ("Okay, I'll suggest a folder for new downloads and Save windows." if on else
                    "Okay, no more automatic folder suggestions. Ask me where should this go whenever you want one.")

    async def phone_connected(self, ws) -> None:
        await ws.send_text(json.dumps({"kind": "settings", "folder_suggestions": self.automatic}))
        for suggestion in self.state.new_downloads.values():
            await ws.send_text(json.dumps({"kind": "download", **suggestion}))
        if self.state.save_suggestion:
            await ws.send_text(json.dumps({"kind": "save_panel", **self.state.save_suggestion}))
        if self.save_choice == "asked":
            await ws.send_text(json.dumps({"kind": "save_ask", "file": self.open_save_panel,
                                           "app": self.save_panel_event.get("app", "")}))

    async def from_phone(self, message: dict) -> None:
        if message["kind"] == "set_folder_suggestions":
            await self.set_automatic(bool(message.get("on")))
            return
        if message["kind"] == "save_here":
            try:
                await self.save_here()
            except (AgentOffline, AgentError) as e:
                await self.hub.push_phone("card", title="Couldn't save there", detail=str(e) or "The computer isn't connected.")
            return
        if message["kind"] == "dismiss_save":
            await self._clear_save_suggestion()
            return
        if message["kind"] == "save_ask":
            await self.answer_save_ask(bool(message.get("yes")))
            return
        suggestion = self.state.new_downloads.get(message.get("file", ""))
        if suggestion is None:
            return
        if message["kind"] == "keep_download":
            del self.state.new_downloads[suggestion["file"]]
            await self.hub.push_phone("download_done", file=suggestion["file"])
            return
        try:
            result = await tidy.move(self.hub, self.state, self.savings, [suggestion])
        except (AgentOffline, AgentError) as e:
            await self.hub.push_phone("card", title="Couldn't move the file", detail=str(e) or "The computer isn't connected.")
            return
        if result["problems"]:
            await self.hub.push_phone("card", title="The file wasn't moved", detail=result["problems"][0])

    def voice_context(self) -> str:
        """So "yes, move it", "put it in Desktop instead" or "save it there" works by voice."""
        context = ""
        if time.time() - self.state.last_move_at < UNDO_MOVE_SECONDS:
            context += " Dock just moved files, so \"undo\" or \"put them back\" means undo_last_action."
        if self.save_choice == "asked":
            context += (f" A Save window is open for \"{self.open_save_panel}\", and the phone is asking whether"
                        " Dock should suggest a folder. If the user says yes, call suggest_folders.")
        if self.state.save_suggestion:
            s = self.state.save_suggestion
            context += (f" A Save window is open in {s['app']} for \"{s['file']}\", and Dock suggested the folder"
                        f" \"{s['to']}\". \"Save it there\" or \"yes, save it\" means put_in_folder.")
        if not self.state.new_downloads:
            return context
        waiting = "; ".join(f"file \"{s['file']}\" to folder \"{s['to']}\"" + (" (new folder)" if s["new_folder"] else "")
                            for s in self.state.new_downloads.values())
        return context + (f" New downloads with a suggested folder, not moved yet: {waiting}."
                " If the user says move it or yes, call put_in_folder (moves can stay empty).")
