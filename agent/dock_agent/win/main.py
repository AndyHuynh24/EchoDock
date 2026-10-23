"""Windows desktop agent entry point (scripts\\start.ps1 runs it).

    .venv\\Scripts\\python -m dock_agent.win.main

Environment: DOCK_SERVER (default ws://localhost:8000), DOCK_TOKEN.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import webview
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from dock_agent import link, speech, tidy
from dock_agent.win import apps, bubble, hotkey, overlay, savepanel, talk, tray, uia, watch
from dock_agent.win.actions import ACTIONS, ActionError

WELCOMED = Path.home() / ".dock" / "welcomed-windows"


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
    """Run jobs from the server, reconnecting when the connection drops."""
    uia.ready()
    while True:
        try:
            with connect(url) as ws:
                print(f"Connected to {server}")
                link.attach(ws)
                link.send_event("hello", platform="windows", talk_key=hotkey.KEY_NAME)
                tray.set_status(f"Dock is ready · press {hotkey.KEY_NAME} to talk")
                watch.announce_front_app()
                try:
                    for raw in ws:
                        job = json.loads(raw)
                        print(f"Job: {job.get('action')} {job.get('args')}")
                        link.send(handle(job))
                finally:
                    link.detach(ws)
        except (OSError, WebSocketException) as e:
            tray.set_status("Dock can't reach its server…")
            print(f"Not connected ({e}). Retrying in 3 seconds…")
            time.sleep(3)


def _started(server: str, url: str) -> None:
    """Runs once the bubble window exists."""
    bubble.on_focus = tray.set_focus
    bubble.on_listen = talk.toggle
    bubble.on_cancel = talk.cancel
    bubble.started()
    tray.start()
    overlay.start()
    apps.prepare()
    if talk.start():
        print(f"Talk key ready: press {hotkey.KEY_NAME}")
    else:
        print("The talk key couldn't be set up.")
    speech.prepare()
    watch.start()
    tidy.watch_downloads()
    savepanel.start()
    threading.Thread(target=stay_connected, args=(server, url), daemon=True, name="server").start()
    if not WELCOMED.exists():
        time.sleep(2)
        bubble.show_welcome()
        WELCOMED.parent.mkdir(parents=True, exist_ok=True)
        WELCOMED.write_text("yes")


def main() -> None:
    server = os.environ.get("DOCK_SERVER", "ws://localhost:8000").rstrip("/")
    token = os.environ.get("DOCK_TOKEN")
    if not token:
        sys.exit("Please set DOCK_TOKEN to the same value the server uses.")
    url = f"{server}/ws/agent?token={quote(token)}"
    bubble.create()
    webview.start(_started, (server, url), private_mode=True, gui="edgechromium")


if __name__ == "__main__":
    main()
