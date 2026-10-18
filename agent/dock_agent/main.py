"""Dock desktop agent. Connects out to the Dock server, waits for jobs, runs
them, and sends back the result. Reconnects automatically.

Run it from the agent folder:  uv run python -m dock_agent.main
Settings (environment variables):
  DOCK_SERVER  e.g. ws://localhost:8000 (default) or wss://your-domain
  DOCK_TOKEN   the same token the server uses
"""

import json
import os
import sys
import threading
import time
from urllib.parse import quote

from PyObjCTools import AppHelper
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from dock_agent import bubble, link, menubar, overlay, savepanel, speech, talk, tidy, watch
from dock_agent import hotkey
from dock_agent.actions import ACTIONS, ActionError


def handle(job: dict) -> dict:
    action = ACTIONS.get(job.get("action"))
    if action is None:
        return {"id": job.get("id"), "ok": False, "error": "That action isn't allowed."}
    try:
        result = action(**job.get("args", {}))
        return {"id": job["id"], "ok": True, "result": result}
    except ActionError as e:
        return {"id": job["id"], "ok": False, "error": str(e)}
    except Exception as e:
        print(f"Job {job} failed: {e!r}")
        return {"id": job["id"], "ok": False, "error": "Something went wrong on the computer."}


def stay_connected(server: str, url: str) -> None:
    """Connect to the server, run the jobs it sends, and reconnect if the connection drops."""
    while True:
        try:
            with connect(url) as ws:
                print(f"Connected to {server}")
                link.attach(ws)
                link.send_event("hello", platform="mac", talk_key=hotkey.KEY_NAME)
                AppHelper.callAfter(menubar.set_status, f"Dock is ready · press {hotkey.KEY_NAME} to talk")
                watch.announce_front_app()
                try:
                    for raw in ws:
                        job = json.loads(raw)
                        print(f"Job: {job.get('action')} {job.get('args')}")
                        link.send(handle(job))
                finally:
                    link.detach(ws)
        except (OSError, WebSocketException) as e:
            AppHelper.callAfter(menubar.set_status, "Dock can't reach its server…")
            print(f"Not connected ({e}). Retrying in 3 seconds…")
            time.sleep(3)


def main() -> None:
    server = os.environ.get("DOCK_SERVER", "ws://localhost:8000").rstrip("/")
    token = os.environ.get("DOCK_TOKEN")
    if not token:
        sys.exit("Please set DOCK_TOKEN to the same value the server uses.")
    url = f"{server}/ws/agent?token={quote(token)}"

    # The pointer, the bubble and the menu bar need the macOS event loop on the
    # main thread, so the server connection runs on a background thread.
    overlay.start_app()
    menubar.start()
    bubble.on_focus = menubar.set_focus
    bubble.on_listen = talk.toggle
    bubble.on_cancel = talk.cancel
    bubble.start()
    start_talk_key()
    speech.prepare()
    watch.start()
    tidy.watch_downloads()
    savepanel.start()
    threading.Thread(target=stay_connected, args=(server, url), daemon=True).start()
    if first_run():
        bubble.show_welcome()
    overlay.run()


def start_talk_key() -> None:
    """The talk key needs the Accessibility permission; until it's allowed, try again every few seconds."""
    if talk.start():
        print(f"Talk key ready: press {hotkey.KEY_NAME}")
        return
    if not getattr(start_talk_key, "told", False):
        start_talk_key.told = True
        print("The talk key needs the Accessibility permission. Open Dock from the menu bar to allow it.")
    AppHelper.callLater(3, start_talk_key)


def first_run() -> bool:
    """Show the welcome window until everything Dock needs is allowed."""
    from dock_agent import menus
    return not menus.check_permission() or speech.permissions()["microphone"] != "allowed"


if __name__ == "__main__":
    main()
