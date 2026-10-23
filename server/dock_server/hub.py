"""Tracks connected clients (desktop agent, phones) and routes messages between them and the MCP tools."""

import asyncio
import json
import secrets

from starlette.websockets import WebSocket


class AgentOffline(Exception):
    """The desktop agent is not connected."""


class AgentError(Exception):
    """The desktop agent ran the job but reported a problem."""


class Hub:
    def __init__(self, token: str):
        self.token = token
        self.agent: WebSocket | None = None
        self.phones: set[WebSocket] = set()
        self.mac_screens: set[WebSocket] = set()
        self.talked = False  # for the setup page
        # Reported by the agent when it connects.
        self.platform = "mac"
        self.talk_key = "⌥ Space"
        self.pending: dict[int, asyncio.Future] = {}
        self.next_id = 0
        # Optional handlers, set by main.py.
        self.on_agent_event = None
        self.on_phone_message = None
        self.on_phone_connect = None
        self._tasks: set[asyncio.Task] = set()

    def _run_in_background(self, coroutine) -> None:
        """Run a handler without blocking the socket loop."""
        async def safely():
            try:
                await coroutine
            except Exception as e:
                print(f"Handler failed: {e!r}")
        task = asyncio.create_task(safely())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _token_ok(self, ws: WebSocket) -> bool:
        return secrets.compare_digest(ws.query_params.get("token", ""), self.token)

    async def agent_endpoint(self, ws: WebSocket) -> None:
        if not self._token_ok(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        self.agent = ws
        print("Desktop agent connected")
        try:
            async for message in ws.iter_json():
                if "event" in message:
                    if self.on_agent_event:
                        self._run_in_background(self.on_agent_event(message))
                    continue
                future = self.pending.pop(message.get("id"), None)
                if future and not future.done():
                    future.set_result(message)
        finally:
            if self.agent is ws:
                self.agent = None
            print("Desktop agent disconnected")

    async def phone_endpoint(self, ws: WebSocket) -> None:
        if not self._token_ok(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        self.phones.add(ws)
        if ws.query_params.get("screen") == "mac":
            self.mac_screens.add(ws)
        print(f"{'Mac bubble' if ws in self.mac_screens else 'Phone'} connected ({self.real_phones()} phones)")
        if self.on_phone_connect:
            await self.on_phone_connect(ws)
        await self.push_phone("screens", phones=self.real_phones())
        try:
            async for message in ws.iter_json():
                if self.on_phone_message:
                    self._run_in_background(self.on_phone_message(message))
        finally:
            self.phones.discard(ws)
            self.mac_screens.discard(ws)
            print(f"Screen disconnected ({self.real_phones()} phones)")
            await self.push_phone("screens", phones=self.real_phones())

    @property
    def computer(self) -> str:
        """What to call the computer in what Dock says: "Mac" or "PC"."""
        return "PC" if self.platform == "windows" else "Mac"

    @property
    def undo_key(self) -> tuple[str, str]:
        """The app's Undo shortcut, as shown and as spoken."""
        return ("Ctrl+Z", "Control Z") if self.platform == "windows" else ("⌘Z", "Command Z")

    def real_phones(self) -> int:
        """Connected phones, not counting the Mac bubble."""
        return len(self.phones - self.mac_screens)

    async def ask_agent(self, action: str, timeout: float = 5, **args) -> dict:
        """Send a job to the desktop agent and wait for its result."""
        if self.agent is None:
            raise AgentOffline()
        self.next_id += 1
        job_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[job_id] = future
        try:
            await self.agent.send_json({"id": job_id, "action": action, "args": args})
            reply = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise AgentError("The computer took too long to answer.")
        finally:
            self.pending.pop(job_id, None)
        if not reply.get("ok"):
            raise AgentError(reply.get("error", "Something went wrong on the computer."))
        return reply.get("result") or {}

    async def push_phone(self, kind: str, **data) -> None:
        """Show something on every connected phone."""
        message = json.dumps({"kind": kind, **data})
        for phone in list(self.phones):
            try:
                await phone.send_text(message)
            except Exception:
                self.phones.discard(phone)
