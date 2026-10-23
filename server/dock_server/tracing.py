"""Per-request tracing: steps, timings and estimated cost.

One JSON line per request in .data/traces.jsonl. Summarize with
`python -m evals.trace_report`. DOCK_TRACE=off disables it; DOCK_TRACE=log also prints each line.
"""

import contextvars
import json
import os
import threading
import time
import uuid

from dock_server.state import DATA_DIR

TRACE_FILE = DATA_DIR / "traces.jsonl"
KEEP_LINES = 2000
HEADER = "x-dock-trace"
ON = os.environ.get("DOCK_TRACE", "on").lower() != "off"
TO_LOG = os.environ.get("DOCK_TRACE", "on").lower() == "log"

# USD per million tokens (input, output, cache read, cache write), for estimates.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
    "claude-sonnet-4": (3.00, 15.00, 0.30, 3.75),
    "nova-2-lite": (0.30, 2.50, 0.075, 0.0),
    "nova-lite": (0.06, 0.24, 0.015, 0.0),
    "titan-embed-text-v2": (0.02, 0.0, 0.0, 0.0),
}

_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("dock_trace", default=None)
_open: dict[str, dict] = {}
_lock = threading.Lock()


def cost(model: str, usage: dict) -> float:
    prices = next((p for name, p in PRICES.items() if name in model), None)
    if not prices:
        return 0.0
    tokens = (usage.get("inputTokens", 0), usage.get("outputTokens", 0),
              usage.get("cacheReadInputTokens", 0), usage.get("cacheWriteInputTokens", 0))
    return sum(t * p for t, p in zip(tokens, prices)) / 1_000_000


def start(kind: str, said: str) -> dict:
    """Start a trace for one request."""
    trace = {"id": uuid.uuid4().hex[:12], "kind": kind, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "said": said, "steps": [], "_started": time.perf_counter()}
    _open[trace["id"]] = trace
    _current.set(trace)
    return trace


def finish(trace: dict, reply: str, **extra) -> None:
    _open.pop(trace["id"], None)
    trace["seconds"] = round(time.perf_counter() - trace.pop("_started"), 3)
    trace["cost"] = round(sum(s.get("cost", 0) for s in trace["steps"]), 6)
    trace["reply"] = reply[:300]
    trace.update(extra)
    _write(trace)


def step(**fields) -> dict:
    """Add a step to the current request and return it."""
    if not ON:
        return fields
    trace = _current.get()
    if trace is not None and trace["id"] in _open:
        trace["steps"].append(fields)
    else:
        _write({"id": uuid.uuid4().hex[:12], "kind": "step", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "parent": trace["id"] if trace else None, "steps": [fields],
                "seconds": fields.get("seconds", 0), "cost": fields.get("cost", 0)})
    return fields


def model_step(purpose: str, model: str, response: dict, seconds: float) -> None:
    usage = response.get("usage", {})
    output = usage.get("outputTokens", 0)
    step(type="model", purpose=purpose, model=model, seconds=round(seconds, 3),
         input=usage.get("inputTokens", 0), output=output,
         cache_read=usage.get("cacheReadInputTokens", 0), cache_write=usage.get("cacheWriteInputTokens", 0),
         tokens_per_sec=round(output / seconds, 1) if seconds else 0,
         cost=round(cost(model, usage), 6))


def _write(record: dict) -> None:
    if not ON:
        return
    if TO_LOG:
        summary = f"{record.get('kind')} {record.get('said', record.get('purpose', ''))!r} {record.get('seconds', '')} s"
        print(json.dumps({"severity": "ERROR" if record.get("error") else "INFO", "message": summary,
                          "dock_trace": record}), flush=True)
    with _lock:
        try:
            DATA_DIR.mkdir(exist_ok=True)
            with TRACE_FILE.open("a") as f:
                f.write(json.dumps(record) + "\n")
            if TRACE_FILE.stat().st_size > 4_000_000:
                lines = TRACE_FILE.read_text().splitlines()[-KEEP_LINES:]
                TRACE_FILE.write_text("\n".join(lines) + "\n")
        except OSError as e:
            print(f"Couldn't write the trace: {e}")


class TraceRequests:
    """Attach model calls made by a tool to the voice request that called it (x-dock-trace)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(HEADER.encode())
            _current.set(_open.get(given.decode()) if given else None)
        await self.app(scope, receive, send)
