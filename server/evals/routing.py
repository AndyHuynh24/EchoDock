"""Routing eval: does the model pick an accepted tool for each phrase in routing_cases.py?

Uses the live tool list from /mcp and the same prompt and fix_call corrections as
real requests, but runs nothing. Also checks the safety rules. Dock must be running.

    uv run python -m evals.routing
    uv run python -m evals.routing --category safety
    uv run python -m evals.routing --model us.amazon.nova-2-lite-v1:0

Results go to evals/results/ (summary in LATEST.md).
"""

import argparse
import ast
import asyncio
import json
import os
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from dock_server import bedrock, tracing, voice
from dock_server.downloads import NewDownloads
from dock_server.library import Library
from dock_server.main import HEARING_HELP
from dock_server.menu_words import is_risky
from dock_server.state import State
from dock_server.tools import writing
from evals.routing_cases import CASES

REPO = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"
MCP_URL = os.environ.get("DOCK_MCP_URL", "http://127.0.0.1:8000/mcp")

# Default context for every case.
BASE = (" The app in front on the Mac is RStudio."
        " The user's folders include: CS589, stat310, stat525, CS305, CS320, homework, OneDock."
        " Apps open on the Mac: Finder, Preview, RStudio, Safari, TextEdit, VS Code (Code)."
        " Saved workspaces: stat310, stat, cs589." + HEARING_HELP)
SELECTED = (" The user has 412 characters of text selected in TextEdit: \"this\" or \"it\" most likely means "
            "that text (improve_writing changes it, read reads it).")
MAIL_PLAN = (" Dock just proposed an email clean-up (9 emails): \"yes\", \"do it\" or \"clean it up\" means "
             "clean_up_email with confirm true, never do_app_action.")
TODO_OFFER = (" Dock offered to add these to-dos from email: 'Submit STAT 525 HW4'. \"Yes\", \"add it\" or "
              "\"put it on my calendar\" means add_email_todo (with that text if they say which), never notes.")


def _downloads_context(situation: str) -> str:
    d = NewDownloads.__new__(NewDownloads)
    d.state = State()
    d.state.last_move_at = time.time() if situation == "moved" else 0.0
    d.save_choice, d.open_save_panel = ("asked" if situation == "ask" else ""), "hw4.pdf"
    if situation == "dl":
        d.state.new_downloads["hw4.pdf"] = {"file": "hw4.pdf", "to": "Documents/school/stat310", "new_folder": False, "why": ""}
    if situation == "save":
        d.state.save_suggestion = {"file": "lab notes.rtf", "to": "Documents/school/stat310/labs", "new_folder": False, "app": "TextEdit"}
    return d.voice_context()


def _writing_context(situation: str) -> str:
    now = time.time()
    writing._search = {"query": "how to cite a website in APA", "at": now} if situation == "searched" else None
    writing._suggestion = ({"pid": 1, "app": "TextEdit", "original": "hey professor", "new": "Hey professor", "fix": True, "at": now}
                           if situation == "suggested" else None)
    return writing.voice_context()


def _library_context(situation: str) -> str:
    if situation != "answered":
        return ""
    library = Library(hub=None)
    library.last_sources = [{"kind": "file", "ref": "file:x", "title": "HW3_CMPSCI_589_Fall2026.pdf", "who": "",
                             "at": "", "folder": "CS589", "link": ""},
                            {"kind": "email", "ref": "email:1", "title": "HW3 deadline extended", "who": "Prof. Nancy Lee",
                             "at": "", "folder": "", "link": ""}]
    library.last_at = time.time()
    return library.voice_context()


def context_for(situation: str) -> str:
    return (_library_context(situation) + BASE + (SELECTED if situation in ("selected", "suggested") else "")
            + (MAIL_PLAN if situation == "mailplan" else "") + (TODO_OFFER if situation == "todo" else "")
            + _writing_context(situation) + _downloads_context(situation)
            + datetime.now().strftime(" Now: %A, %B %-d, %Y, %-I:%M %p (%Y-%m-%d %H:%M)."))


def picked_name(call: dict | None) -> str:
    if not call:
        return "(none)"
    if call["name"] == "search_web":
        return "search_web:go" if call["input"].get("go") else "search_web"
    return call["name"]


def safety_checks() -> list[tuple[str, bool]]:
    """Safety rules, checked without a model."""
    checks = []
    for title in ("Quit RStudio", "Move to Trash", "Empty Trash…", "Delete", "Erase", "Log Out", "Shut Down…",
                  "Restart…", "Close Window", "Revert to Saved", "Discard Changes"):
        checks.append((f'"do it" never clicks "{title}"', is_risky(title, "do it")))
    checks.append(('"close this window" may click "Close Window"', not is_risky("Close Window", "close this window")))
    checks.append(('"export" is not risky', not is_risky("Export…", "do it")))
    # The agent's allowlist must not include destructive actions.
    for source in (REPO / "agent/dock_agent/actions.py", REPO / "agent/dock_agent/win/actions.py"):
        tree = ast.parse(source.read_text())
        names = next([k.value for k in node.value.keys] for node in ast.walk(tree)
                     if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ACTIONS")
        bad = [n for n in names if re.search(r"delete|remove|trash|erase|shell|exec|command|password|send_mail", n)]
        checks.append((f"{source.relative_to(REPO)}: {len(names)} actions, none deletes or runs commands ({', '.join(bad) or 'ok'})",
                       not bad))
    return checks


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=bedrock.ROUTER_MODEL_ID)
    parser.add_argument("--category", default="")
    args = parser.parse_args()
    tracing.ON = False
    cases = [c for c in CASES if not args.category or c[0] == args.category]

    token = (REPO / ".dock-token").read_text().strip()
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    async with http, Client(streamable_http_client(MCP_URL, http_client=http)) as mcp:
        listed = await mcp.list_tools()
    tools = [{"toolSpec": {"name": t.name, "description": t.description or "", "inputSchema": {"json": t.input_schema}}}
             for t in listed.tools] + [voice.REPLY_TOOL]
    print(f"{len(listed.tools)} MCP tools · {len(cases)} cases · model {args.model}\n")

    rows = []
    for category, phrase, accepted, situation, before in cases:
        context = context_for(situation)
        messages = before + [{"role": "user", "content": [{"text": phrase}]}]
        started = time.perf_counter()
        response = await asyncio.to_thread(bedrock.converse, messages, voice.SYSTEM, tools, 300, True,
                                           args.model, context, "eval")
        seconds = time.perf_counter() - started
        calls = [b["toolUse"] for b in response["output"]["message"]["content"] if "toolUse" in b]
        first_pick = picked_name(calls[0] if calls else None)
        for call in calls:
            voice.fix_call(call, phrase, context)
        picked = picked_name(calls[0] if calls else None)
        usage = response["usage"]
        rows.append({"category": category, "phrase": phrase, "situation": situation, "accepted": sorted(accepted),
                     "picked": picked, "model_picked": first_pick, "ok": picked in accepted,
                     "input": json.dumps(calls[0]["input"]) if calls else "", "seconds": round(seconds, 3),
                     "tokens_in": usage["inputTokens"], "tokens_out": usage["outputTokens"],
                     "cache_read": usage.get("cacheReadInputTokens", 0), "cache_write": usage.get("cacheWriteInputTokens", 0),
                     "cost": tracing.cost(args.model, usage)})
        r = rows[-1]
        fixed = f" (fix_call: {first_pick} →)" if first_pick != picked else ""
        print(f"{'✓' if r['ok'] else '✗'} [{category}] {phrase!r:58} -> {picked}{fixed} {r['input']}"[:190])

    checks = safety_checks()
    print("\nSafety rules (plain code)")
    for name, ok in checks:
        print(f"  {'✓' if ok else '✗'} {name}")

    summary = _summary(rows, checks, args.model, len(listed.tools))
    print("\n" + summary)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    (RESULTS / f"routing-{stamp}.json").write_text(json.dumps({"model": args.model, "cases": rows,
                                                               "safety": checks}, indent=1))
    if not args.category:
        (RESULTS / "LATEST.md").write_text(f"# Latest routing eval ({stamp})\n\n```text\n{summary}\n```\n")


def _summary(rows: list[dict], checks: list, model: str, tool_count: int) -> str:
    passed = sum(r["ok"] for r in rows)
    seconds = sorted(r["seconds"] for r in rows)
    prompt = sum(r["tokens_in"] + r["cache_read"] + r["cache_write"] for r in rows)
    lines = [f"Model: {model} · {tool_count} MCP tools",
             f"Accuracy: {passed}/{len(rows)} ({passed / len(rows):.1%}) picked a right tool",
             f"  fix_call changed the model's pick in {sum(r['picked'] != r['model_picked'] for r in rows)} cases; "
             f"the model alone got {sum(r['model_picked'] in r['accepted'] for r in rows)}/{len(rows)}"]
    by_category = defaultdict(list)
    for r in rows:
        by_category[r["category"]].append(r["ok"])
    lines += [f"  {name:17} {sum(oks)}/{len(oks)}" for name, oks in by_category.items()]
    lines += [f"Speed: median {statistics.median(seconds):.2f} s · p95 {seconds[min(len(seconds) - 1, int(0.95 * len(seconds)))]:.2f} s"
              f" · slowest {seconds[-1]:.2f} s",
              f"Tokens: {sum(r['tokens_in'] for r in rows)} in · {sum(r['tokens_out'] for r in rows)} out · "
              f"{sum(r['cache_read'] for r in rows) / prompt:.0%} of prompt tokens from the cache",
              f"Cost: ${statistics.mean(r['cost'] for r in rows):.4f} per request (estimated) · ${sum(r['cost'] for r in rows):.3f} for this run",
              f"Safety rules: {sum(ok for _, ok in checks)}/{len(checks)} pass"]
    failed = [r for r in rows if not r["ok"]]
    if failed:
        lines.append("Wrong:")
        lines += [f"  [{r['category']}] {r['phrase']!r} -> {r['picked']} (wanted {' or '.join(r['accepted'])})" for r in failed]
    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())
