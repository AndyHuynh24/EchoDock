"""Starts the Dock server: one web app that serves

- /mcp        the MCP endpoint (Streamable HTTP) that Alexa+ or the simulated
              Alexa+ voice mode calls
- /api/voice  simulated Alexa+: the phone sends what the user said
- /ws/agent   WebSocket for the desktop agent on the laptop
- /ws/phone   WebSocket for the phone web app
- /setup      the setup page with a QR code for the phone (only on the Mac itself)
- /           the phone web app itself (files in server/static)

/mcp and /api need "Authorization: Bearer <DOCK_TOKEN>". The WebSockets take
?token=<DOCK_TOKEN>. The installed phone app lives at its own fixed address
(see webapp.py) and may call /api from there.

Run it from the server folder:  uv run python -m dock_server.main
"""

import asyncio
import os
import secrets
import sys
import time
from datetime import datetime
import traceback
from pathlib import Path

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from dock_server import setup_page, tunnel, voice, webapp
from dock_server.downloads import NewDownloads
from dock_server.briefing import Briefing
from dock_server.mail import Mail
from dock_server.focus import FocusMode
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.calendar_link import Calendar
from dock_server.notes import Notes
from dock_server.pad import Pad
from dock_server.savings import Savings
from dock_server.state import State
from dock_server.timefmt import strftime
from dock_server.tools import app_help, computer, focus, reading, recap, tidy, workspaces, writing

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Phone taps that ask Dock to do something (not status updates like presence).
FOLDER_NAMES_SECONDS = 600
OPEN_APPS_SECONDS = 20
WORKSPACES_SECONDS = 60
APP_NAMES = {"Code": "VS Code (Code)"}  # macOS names some apps differently from how people say them
# Speech-to-text gets names and numbers wrong in the same ways again and again.
HEARING_HELP = (
    " Important: the user's words come from speech-to-text, which often mishears names and "
    "numbers. Before you pick a tool, fix them to the closest real folder, app or workspace "
    "name listed above, by how they sound: 'fighter' or 'finer' is Finder, 'start 3:10', "
    "'stat 3 10' or 'stat three ten' is stat310, 'CS 589' is CS589. Then use the real name. "
    "Only ask what they meant when no real name sounds close."
)
STATIC_PAGE_FILES = ("index.html", "app.js", "style.css", "focus.js")


def page_version() -> str:
    """Changes whenever the phone page's files change."""
    import hashlib
    digest = hashlib.sha1()
    for name in STATIC_PAGE_FILES:
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:12]
DOCK_REQUESTS = ("press", "move", "move_download", "keep_download",
                 "start_focus", "start_break", "week_report")

INSTRUCTIONS = (
    "Dock is a desk assistant. It controls the user's computer (open folders, "
    "apps and files) and helps inside the app they are using. It also has an "
    "optional focus mode. Keep spoken answers to one or two short sentences."
)


AWS_LOGIN_EXPIRED = "My AI login has expired. On the {computer}, open {terminal} and run aws login, then ask me again."


def _aws_login_problem(error: BaseException) -> bool:
    """True if the AI failed because the AWS login expired or is missing."""
    while error is not None:
        name = type(error).__name__
        if name in ("LoginRefreshRequired", "NoCredentialsError", "TokenRetrievalError", "UnauthorizedSSOTokenError") \
                or "ExpiredToken" in str(error) or "aws login" in str(error):
            return True
        error = error.__cause__ or error.__context__
    return False


class TokenAuth:
    """Refuses requests to /mcp and /api without the right bearer token."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(("/mcp", "/api")):
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not secrets.compare_digest(given, self.expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class AllowPhoneApp:
    """Lets the installed phone app (at its fixed web address, see webapp.py)
    call /api on this server. Browsers block that unless the server says the
    app's address is allowed (CORS). The bearer token is still required."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        given = dict(scope.get("headers", [])).get(b"origin", b"").decode()
        if scope["type"] != "http" or not webapp.origin() or given != webapp.origin():
            await self.app(scope, receive, send)
            return
        allow = [(b"access-control-allow-origin", given.encode()), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS":  # the browser asks first
            await send({"type": "http.response.start", "status": 204, "headers": allow + [
                (b"access-control-allow-methods", b"GET, POST"),
                (b"access-control-allow-headers", b"authorization, content-type"),
                (b"access-control-max-age", b"86400")]})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_allowed(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + allow}
            await send(message)

        await self.app(scope, receive, send_allowed)


def create_app(token: str, port: int):
    hub = Hub(token)
    state = State()
    savings = Savings(hub)
    mcp = MCPServer("Dock", instructions=INSTRUCTIONS)
    computer.register(mcp, hub, savings)
    workspaces.register(mcp, hub, savings)
    app_help.register(mcp, hub, state, savings)
    new_downloads = NewDownloads(hub, state, savings)
    new_downloads.register(mcp)
    reading.register(mcp, hub)
    writing.register(mcp, hub)
    focus_mode = FocusMode(hub, state)
    notes = Notes(hub)
    notes.register(mcp)
    calendar = Calendar(hub, notes)
    notes.calendar = calendar  # (to-dos with a time go on the calendar)
    calendar.register(mcp)
    mail = Mail(hub, focus_mode, notes, calendar)
    mail.register(mcp)
    briefing = Briefing(hub, calendar, mail, notes, focus_mode)
    briefing.register(mcp)
    focus.register(mcp, focus_mode, notes, calendar, mail)
    recap.register(mcp, hub, state, savings, focus_mode, notes)

    pad = Pad(hub, state, savings)
    pad.downloads = new_downloads

    async def on_agent_event(event: dict) -> None:
        if event["event"] == "hello":  # the agent says which computer it's on
            hub.platform = str(event.get("platform") or "mac")
            hub.talk_key = str(event.get("talk_key") or hub.talk_key)
            await hub.push_phone("platform", platform=hub.platform, talk_key=hub.talk_key)
        elif event["event"] == "front_app":
            await pad.front_app_changed(event)
            await briefing.on_activity()  # (the user is at the computer: maybe the morning briefing)
        elif event["event"] == "new_download":
            await new_downloads.on_new(event)
        elif event["event"] == "save_panel":
            await new_downloads.on_save_panel(event)
        elif event["event"] == "save_panel_closed":
            await new_downloads.on_save_panel_closed(event)
        elif event["event"] == "save_panel_folder_changed":
            await new_downloads.on_save_panel_folder_changed(event)
        elif event["event"] == "save_panel_left":
            await new_downloads.on_save_panel_left(event)

    async def on_phone_message(message: dict) -> None:
        kind = message.get("kind")
        if kind in ("open_mac_chat", "close_mac_chat"):
            # The phone is the trigger: the chat box opens on the Mac, for the Mac's keyboard.
            try:
                await hub.ask_agent("chat_box", open=kind == "open_mac_chat")
                if kind == "open_mac_chat":
                    await hub.push_phone("mac_chat", ok=True)
            except (AgentOffline, AgentError):
                await hub.push_phone("mac_chat", ok=False)
            return
        if kind == "mac_typing":
            await hub.push_phone("stop_listening")  # typing on the Mac: the phone stops listening
            return
        if kind == "speech_done":
            await hub.push_phone("speech_done", **{"from": message.get("from")})  # one screen finished saying it: the others' card goes too
            return
        if kind == "screen_info":
            print("Phone screen: " + " ".join(f"{k}={message.get(k)}" for k in ("mode", "fullscreen", "view", "screen", "insets", "angle")))
            return
        if kind in DOCK_REQUESTS:
            # The user asked Dock for something else, so drop "Want Dock to suggest a folder?"
            await new_downloads.skip_save_ask("asked Dock for something else")
        if kind == "press":
            await pad.press(message)
        elif kind == "move":
            await tidy.move_from_phone(hub, state, savings, message)
        elif kind in ("move_download", "keep_download", "save_here", "dismiss_save", "save_ask", "set_folder_suggestions"):
            await new_downloads.from_phone(message)
        elif kind in ("mail_todo", "mail_unsubscribe", "mail_cleanup", "mail_cleanup_cancel"):
            await mail.from_phone(message)
        elif kind == "briefing":
            await briefing.from_phone(message)
        elif kind == "writing_use":
            await writing.from_phone(hub, message)
        elif kind == "search_go":
            await writing.search_from_phone(hub, message)
        elif kind in ("start_focus", "pause_focus", "resume_focus", "end_focus", "presence", "focus_finished",
                      "start_break", "week_report"):
            await focus_mode.from_phone(message)

    # Phones that stay open get told when the page changes too (checked every few seconds).
    version_watch = []

    async def tell_new_version() -> None:
        current = page_version()
        while True:
            await asyncio.sleep(5)
            if page_version() != current:
                # (Wait for the installed app's online copy to be updated first, see webapp.py.)
                await asyncio.sleep(15)
                current = page_version()
                await hub.push_phone("version", id=current)

    async def on_phone_connect(ws) -> None:
        # Which version of the page is current: an open phone page reloads itself
        # when Dock was updated, instead of running its old copy.
        await ws.send_json({"kind": "version", "id": page_version()})
        await ws.send_json({"kind": "platform", "platform": hub.platform, "talk_key": hub.talk_key})
        if not version_watch:
            version_watch.append(asyncio.get_running_loop().create_task(tell_new_version()))
        calendar.ensure_watch()
        mail.ensure_watch()
        notes.ensure_watch()
        await briefing.on_activity()
        await pad.phone_connected(ws)
        await focus_mode.phone_connected(ws)
        await savings.push(ws)
        await new_downloads.phone_connected(ws)

    hub.on_agent_event = on_agent_event
    hub.on_phone_message = on_phone_message
    hub.on_phone_connect = on_phone_connect

    mcp_url = f"http://127.0.0.1:{port}/mcp"

    # The user's own folder names, so the AI can fix speech mistakes ("Start 310"
    # is their stat310 folder). Asked from the Mac at most every 10 minutes.
    folder_names = {"at": 0.0, "names": []}

    async def known_folders() -> list[str]:
        if time.time() - folder_names["at"] > FOLDER_NAMES_SECONDS:
            try:
                folder_names["names"] = (await hub.ask_agent("folder_names", timeout=5))["names"]
                folder_names["at"] = time.time()
            except (AgentOffline, AgentError):
                pass
        return folder_names["names"]

    # The same for open apps and saved workspaces ("fighter" is Finder, "start
    # 3:10" is the stat310 workspace). These change more often, so asked more often.
    known = {"apps": (0.0, []), "workspaces": (0.0, [])}

    async def known_names(kind: str, action: str, seconds: float) -> list[str]:
        at, names = known[kind]
        if time.time() - at > seconds:
            try:
                names = (await hub.ask_agent(action, timeout=3))["names"]
                known[kind] = (time.time(), names)
            except (AgentOffline, AgentError):
                pass
        return names

    async def voice_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"reply": "I didn't catch that.", "quiet": False})
        print(f"Voice: {text!r}")
        # Every screen shows the same thing: the others show this request and its answer too.
        screen = {"from": body.get("screen", "")}
        await hub.push_phone("asking", text=text, **screen)
        hub.talked = True
        quiet = False
        try:
            context = ""
            if hub.platform == "windows":
                context += (" The computer is a Windows PC: where these instructions say Mac, they mean this PC "
                            "(File Explorer is its Finder, Ctrl is its Command key).")
            try:
                # So "where's Programmer?" is a feature of this app, and "how do I check my
                # costs?" on the AWS console in Safari is about that page.
                front = await hub.ask_agent("front_window", timeout=1.5)
                context += f" The app in front on the Mac is {front['app']}"
                context += f", and its window is \"{front['title'][:100]}\"." if front.get("title") else "."
            except (AgentOffline, AgentError):
                if state.pad.get("app"):
                    context += f" The app in front on the Mac is {state.pad['app']}."
            context += new_downloads.voice_context()
            context += mail.voice_context()
            context += writing.voice_context()
            try:
                selected = await hub.ask_agent("selection_size", timeout=1.5)
                if selected["chars"]:
                    context += (f" The user has {selected['chars']} characters of text selected in {selected['app']}: "
                                "\"this\" or \"it\" most likely means that text (improve_writing changes it, read reads it).")
            except (AgentOffline, AgentError):
                pass
            context += await asyncio.to_thread(calendar.voice_context)
            context += strftime(datetime.now(), " Now: %A, %B %-d, %Y, %-I:%M %p (%Y-%m-%d %H:%M).")
            names = await known_folders()
            if names:
                context += f" The user's folders include: {', '.join(names)}."
            apps = [APP_NAMES.get(a, a) for a in await known_names("apps", "open_app_names", OPEN_APPS_SECONDS)]
            if apps:
                context += f" Apps open on the Mac: {', '.join(apps)}."
            spaces = await known_names("workspaces", "list_workspaces", WORKSPACES_SECONDS)
            if spaces:
                context += f" Saved workspaces: {', '.join(spaces)}."
            context += HEARING_HELP
            reply, quiet = await voice.answer(text, mcp_url, token, context=context)
            # Unless that answered it (by calling suggest_folders), the question is now stale.
            await new_downloads.skip_save_ask("asked Dock for something else")
        except Exception as e:
            traceback.print_exc()
            reply = (AWS_LOGIN_EXPIRED.format(computer=hub.computer, terminal="PowerShell" if hub.platform == "windows" else "Terminal")
                     if _aws_login_problem(e)
                     else "Sorry, something went wrong on my side. Please try again.")
        print(f"Reply: {reply!r}" + (" (quiet)" if quiet else ""))
        await hub.push_phone("answered", text=text, reply=reply, quiet=quiet, spoken=bool(body.get("spoken")), **screen)
        return JSONResponse({"reply": reply, "quiet": quiet})

    # Remote MCP clients (Alexa+) reach /mcp through the public address, whose name the
    # SDK's localhost-only Host check would refuse. /mcp needs the secret token anyway,
    # which is what keeps other web pages and people out.
    app = mcp.streamable_http_app(stateless_http=True, json_response=True,
                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app.router.routes.append(Route("/api/voice", voice_endpoint, methods=["POST"]))
    app.router.routes.append(WebSocketRoute("/ws/agent", hub.agent_endpoint))
    app.router.routes.append(WebSocketRoute("/ws/phone", hub.phone_endpoint))
    app.router.routes.extend(setup_page.routes(hub, token, STATIC_DIR, calendar, new_downloads, mail, briefing))
    app.router.routes.append(Mount("/", StaticFiles(directory=STATIC_DIR, html=True)))
    return AllowPhoneApp(TokenAuth(app, token))


def main() -> None:
    token = os.environ.get("DOCK_TOKEN")
    if not token:
        sys.exit("Please set DOCK_TOKEN first, for example:  export DOCK_TOKEN=$(openssl rand -hex 16)")
    port = int(os.environ.get("PORT", "8000"))
    tunnel.start(port)
    webapp.start(STATIC_DIR)
    print(f"Dock server on http://localhost:{port}. Setup page: http://localhost:{port}/setup")
    uvicorn.run(create_app(token, port), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
