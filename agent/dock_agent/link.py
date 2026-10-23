"""Shared, thread-safe connection to the server for sending events."""

import json
import threading

_ws = None
_lock = threading.Lock()


def attach(ws) -> None:
    global _ws
    with _lock:
        _ws = ws


def detach(ws) -> None:
    global _ws
    with _lock:
        if _ws is ws:
            _ws = None


def send(message: dict) -> None:
    with _lock:
        if _ws is None:
            return
        try:
            _ws.send(json.dumps(message))
        except Exception as e:
            print(f"Couldn't send to the server: {e!r}")


def send_event(kind: str, **data) -> None:
    send({"event": kind, **data})
