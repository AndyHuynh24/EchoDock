"""Dock server entry point.

Serves the MCP endpoint (/mcp, Streamable HTTP), the voice API (/api/voice),
WebSockets for the desktop agent and phones, the setup page and the phone web app.

Run from the server folder:  uv run python -m dock_server.main
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

from dock_server import setup_page, tracing, tunnel, voice, webapp
from dock_server.downloads import NewDownloads
from dock_server.briefing import Briefing
from dock_server.library import Library
from dock_server.mail import DEMO as mail_demo, Mail
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
# Phone messages that run an action
FOLDER_NAMES_SECONDS = 600
OPEN_APPS_SECONDS = 20
WORKSPACES_SECONDS = 60
APP_NAMES = {"Code": "VS Code (Code)"}
# Common speech-to-text mistakes.
HEARING_HELP = (
    " Important: the user's words come from speech-to-text, which often mishears names and "
    "numbers. Before you pick a tool, fix them to the closest real folder, app or workspace "
    "name listed above, by how they sound: 'fighter' or 'finer' is Finder, 'start 3:10', "
    "'stat 3 10' or 'stat three ten' is stat310, 'CS 589' is CS589. Then use the real name. "
    "Only ask what they meant when no real name sounds close."
)
STATIC_PAGE_FILES = ("index.html", "app.js", "style.css", "focus.js")


def page_version() -> str:
    """Changes whenever the static files change."""
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
    """True if Bedrock failed because the AWS login expired or is missing."""
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
    """Allow the hosted phone app to call /api (CORS). The token is still required."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        given = dict(scope.get("headers", [])).get(b"origin", b"").decode()
        if scope["type"] != "http" or not webapp.origin() or given != webapp.origin():
            await self.app(scope, receive, send)
            return
        allow = [(b"access-control-allow-origin", given.encode()), (b"vary", b"Origin")]
        if scope["method"] == "OPTIONS":
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
    notes.calendar = calendar
    calendar.register(mcp)
    mail = Mail(hub, focus_mode, notes, calendar)
    mail.register(mcp)
    library = Library(hub, mail, notes, calendar)
    library.register(mcp)
    briefing = Briefing(hub, calendar, mail, notes, focus_mode)
    briefing.register(mcp)
    focus.register(mcp, focus_mode, notes, calendar, mail)
    recap.register(mcp, hub, state, savings, focus_mode, notes)

    pad = Pad(hub, state, savings)
    pad.downloads = new_downloads

    async def on_agent_event(event: dict) -> None:
        if event["event"] == "hello":
            hub.platform = str(event.get("platform") or "mac")
            hub.talk_key = str(event.get("talk_key") or hub.talk_key)
            await hub.push_phone("platform", platform=hub.platform, talk_key=hub.talk_key)
        elif event["event"] == "front_app":
            await pad.front_app_changed(event)
            await briefing.on_activity()
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
            try:
                await hub.ask_agent("chat_box", open=kind == "open_mac_chat")
                if kind == "open_mac_chat":
                    await hub.push_phone("mac_chat", ok=True)
            except (AgentOffline, AgentError):
                await hub.push_phone("mac_chat", ok=False)
            return
        if kind == "mac_typing":
            await hub.push_phone("stop_listening")
            return
        if kind == "listening":
            await hub.push_phone("listening", on=bool(message.get("on")), **{"from": message.get("from")})
            return
        if kind == "speech_done":
            await hub.push_phone("speech_done", **{"from": message.get("from")})
            return
        if kind == "close_card":
            # Close a card on every screen.
            await hub.push_phone("close_card", id=str(message.get("id", ""))[:40])
            return
        if kind == "screen_info":
            print("Phone screen: " + " ".join(f"{k}={message.get(k)}" for k in ("mode", "fullscreen", "view", "screen", "insets", "angle")))
            return
        if kind in DOCK_REQUESTS:
            # A new request replaces the pending folder suggestion.
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

    # Tell open phones when the page changes.
    version_watch = []

    async def tell_new_version() -> None:
        current = page_version()
        while True:
            await asyncio.sleep(5)
            if page_version() != current:
                await asyncio.sleep(15)
                current = page_version()
                await hub.push_phone("version", id=current)

    async def on_phone_connect(ws) -> None:
        await ws.send_json({"kind": "version", "id": page_version()})
        await ws.send_json({"kind": "platform", "platform": hub.platform, "talk_key": hub.talk_key,
                            "demo": mail_demo})
        if not version_watch:
            version_watch.append(asyncio.get_running_loop().create_task(tell_new_version()))
        calendar.ensure_watch()
        mail.ensure_watch()
        notes.ensure_watch()
        library.ensure_watch()
        await briefing.on_activity()
        await pad.phone_connected(ws)
        await focus_mode.phone_connected(ws)
        asyncio.get_running_loop().create_task(send_workspaces(ws))

    async def send_workspaces(ws) -> None:
        """Saved workspace names, for the face's suggestions."""
        try:
            await ws.send_json({"kind": "workspaces", "names": await known_names("workspaces", "list_workspaces", WORKSPACES_SECONDS)})
        except Exception:
            pass
        await savings.push(ws)
        await new_downloads.phone_connected(ws)

    hub.on_agent_event = on_agent_event
    hub.on_phone_message = on_phone_message
    hub.on_phone_connect = on_phone_connect

    mcp_url = f"http://127.0.0.1:{port}/mcp"

    # Folder names help correct speech mistakes. Refreshed at most every 10 minutes.
    folder_names = {"at": 0.0, "names": []}

    async def known_folders() -> list[str]:
        if time.time() - folder_names["at"] > FOLDER_NAMES_SECONDS:
            try:
                folder_names["names"] = (await hub.ask_agent("folder_names", timeout=5))["names"]
                folder_names["at"] = time.time()
            except (AgentOffline, AgentError):
                pass
        return folder_names["names"]

    # Same for open apps and saved workspaces.
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

    async def heard_endpoint(request: Request) -> JSONResponse:
        """Test remote (static/remote.html): use the tapped phrase as the transcript."""
        text = str((await request.json()).get("text", "")).strip()[:300]
        if text:
            print(f"Remote: {text!r}")
            await hub.push_phone("heard", text=text)
        return JSONResponse({"ok": bool(text)})

    async def skip_timer_endpoint(request: Request) -> JSONResponse:
        """Test remote: end the focus session in 3 seconds."""
        return JSONResponse({"ok": await focus_mode.skip_to_end(3)})

    async def voice_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"reply": "I didn't catch that.", "quiet": False})
        print(f"Voice: {text!r}")
        # Mirror the request and answer on every screen.
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
                front = await hub.ask_agent("front_window", timeout=1.5)
                context += f" The app in front on the Mac is {front['app']}"
                context += f", and its window is \"{front['title'][:100]}\"." if front.get("title") else "."
            except (AgentOffline, AgentError):
                if state.pad.get("app"):
                    context += f" The app in front on the Mac is {state.pad['app']}."
            context += new_downloads.voice_context()
            context += mail.voice_context()
            context += writing.voice_context()
            context += library.voice_context()
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
            await new_downloads.skip_save_ask("asked Dock for something else")
        except Exception as e:
            traceback.print_exc()
            reply = (AWS_LOGIN_EXPIRED.format(computer=hub.computer, terminal="PowerShell" if hub.platform == "windows" else "Terminal")
                     if _aws_login_problem(e)
                     else "Sorry, something went wrong on my side. Please try again.")
        print(f"Reply: {reply!r}" + (" (quiet)" if quiet else ""))
        await hub.push_phone("answered", text=text, reply=reply, quiet=quiet, spoken=bool(body.get("spoken")), **screen)
        return JSONResponse({"reply": reply, "quiet": quiet})

    # Remote MCP clients use the public hostname; /mcp is protected by the token instead of the Host check.
    app = mcp.streamable_http_app(stateless_http=True, json_response=True,
                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app.router.routes.append(Route("/api/voice", voice_endpoint, methods=["POST"]))
    app.router.routes.append(Route("/api/heard", heard_endpoint, methods=["POST"]))
    app.router.routes.append(Route("/api/skip_timer", skip_timer_endpoint, methods=["POST"]))
    app.router.routes.append(WebSocketRoute("/ws/agent", hub.agent_endpoint))
    app.router.routes.append(WebSocketRoute("/ws/phone", hub.phone_endpoint))
    app.router.routes.extend(setup_page.routes(hub, token, STATIC_DIR, calendar, new_downloads, mail, briefing))
    app.router.routes.append(Mount("/", StaticFiles(directory=STATIC_DIR, html=True)))
    return AllowPhoneApp(TokenAuth(tracing.TraceRequests(app), token))


def main() -> None:
    token = os.environ.get("DOCK_TOKEN")
    if not token:
        sys.exit("Please set DOCK_TOKEN first, for example:  export DOCK_TOKEN=$(openssl rand -hex 16)")
    port = int(os.environ.get("PORT", "8000"))
    tunnel.start(port)
    webapp.start(STATIC_DIR)
    print(f"Dock server on http://localhost:{port}. Setup page: http://localhost:{port}/setup")
    # Use DOCK_HOST=0.0.0.0 in a container.
    uvicorn.run(create_app(token, port), host=os.environ.get("DOCK_HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
