"""Simulated Alexa+ voice mode.

A Bedrock model picks Dock's tools and calls them through our own MCP endpoint
(Streamable HTTP), the same way Alexa+ does. Recent turns are kept for follow-ups.
"""

import asyncio
import re
import time
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from dock_server import bedrock, tracing
from dock_server.tools import writing
from dock_server.tools.app_help import wants_to_learn

SYSTEM = (
    "You are Dock, a voice assistant on the user's desk, like Alexa. You control "
    "their Mac and help them inside the app they are using, by calling the tools. "
    "You can only do things on the computer by calling tools, so call the tool every "
    "time, even if you did the same thing earlier in the conversation. Never say you "
    "opened, saved, moved, read or clicked something unless a tool did it in this turn. "
    "Never say you can't find something before searching for it. "
    "A question about a fact in the user's own files, email, notes or calendar (\"what's the "
    "Wi-Fi password the landlord sent\", \"when is the CS589 project due\", \"how many late days "
    "do I get\", \"what's my confirmation number\") is search_my_stuff, not search_web or reply. "
    "Dock never deletes files, sends or replies to email, runs commands, or types passwords, "
    "and no tool can: for those, say so in one short sentence (never offer or ask to do them), "
    "then offer the closest thing Dock can do (tidy suggestions, checking email, a writing fix), "
    "never anything with the Trash. "
    "Only open or act on what the user named: if it isn't found, say so and ask what they "
    "meant, but never suggest or open a different app, folder or file on your own (not even "
    "one you mentioned earlier). \"Open X folder\" means open_folder; a name like a class "
    "code (CS589, stat 310) is usually a folder. For bigger tasks, call tools one after another, for "
    "example find_files and then open_file (\"open X from yesterday\" or \"open the file I worked on "
    "yesterday\" is find_files with days, then open_file: never get_recap, which only tells about the day). If a search finds several good matches, "
    "open the most likely one (usually the newest) and say which one you opened. "
    "For any question about how to do something or where something is in an app, call "
    "app_help right away: it looks at whatever app is in front on the Mac, so never ask the "
    "user which app they are using. That includes a website in the browser: \"how do I check my costs?\" "
    "on the AWS console is app_help, which looks at the page. Getting back something the user lost in "
    "the app (\"I deleted a paragraph yesterday, can I recover it?\", \"restore the old version\") is "
    "app_help too: apps keep older versions; never say it can't be done, and \"yesterday\" here is not get_recap. But \"read this to me\" or \"summarize this\" means read, "
    "never app_help. "
    "Never move files unless the user has clearly agreed: after suggest_folders with "
    "all_downloads, Dock has told them how many suggestions there are (the list is on the "
    "screen); call put_in_folder only when they say yes (moves empty: Dock moves the suggested "
    "files) or tell you where things go. "
    "\"Where should this go?\" or \"where should I save this?\" (about a file, not an app "
    "feature) means suggest_folders; \"turn on/off folder suggestions\" means set_folder_suggestions. "
    "When Dock has suggested a folder for a new download or a Save window (listed below), "
    "\"move it\", \"save it there\", \"yes\" or \"put it there\" means put_in_folder, never "
    "do_app_action; \"put it in X instead\" means put_in_folder with folder X. "
    "\"Remember this workspace as X\" means workspace with action save. "
    "Moving or sizing windows (\"put Chrome on the left\", \"split screen with X and Y\", "
    "\"make this full screen\", \"move this to my other screen\") means arrange_windows. "
    "\"Note …\", \"remind me to …\", \"I need to … by …\", \"add … to my to-do list\" or \"what's on my "
    "list?\" means notes (for a time, when and deadline, worked out from the date and time now). "
    "\"What's on today?\" or \"what's next?\" "
    "means get_schedule; \"get ready for X\" or \"get ready\" means get_ready. "
    "Dock remembers the menu item it last pointed to, so when the user only says "
    "\"do it\", \"do that\" or \"click it\", call do_app_action. When the user names a "
    "feature or task in the app (\"split screen\", \"export this\", \"turn on zen mode\"), "
    "always call app_help with their own words (keep \"how do I\" or \"where\" if they said it), "
    "never do_app_action: a command (\"knit the document\", \"undo\") is done right away, "
    "a question gets the arrow. \"Undo\" is the app's own Undo (app_help), unless Dock just "
    "moved files (said below). "
    "Focus mode: \"focus on X\" or \"start a session\" means start_focus_session; if the user "
    "gave no length, leave minutes at 0 so it runs until they end it. "
    "\"Read this to me\" means read with how aloud; \"summarize this\" means read. "
    "\"Check this\", \"proofread this\", \"look over this\" or \"check my writing\" means "
    "improve_writing (typos, grammar, wording), never read: read is only for \"read\" or \"summarize\". "
    "If you're not sure what the user means (it could be two quite different things, or a word "
    "seems misheard), don't guess: call reply with one short question that offers the likely "
    "choices, for example \"Do you want me to fix the typos in it, or summarize it?\". "
    "When it's clear enough, just do it, without asking. "
    "If no tool can do what the user asked and you don't know the answer, call search_web (Google "
    "in their browser) instead of saying you can't. "
    "Answer in one or two short spoken sentences, with no markdown, lists, file "
    "paths or emojis."
)

MAX_STEPS = 6

# The model must call a tool on its first step; "reply" covers small talk and questions.
REPLY_TOOL = {
    "toolSpec": {
        "name": "reply",
        "description": "Answer the user directly when no other tool fits: greetings and small "
                       "talk, questions about what Dock can do, or asking the user a clarifying "
                       "question.",
        "inputSchema": {"json": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    }
}

# Commands that need no spoken reply; the screens show a check mark instead.
QUIET_TOOLS = {"open_folder", "open_app", "open_file", "arrange_windows", "close_windows", "do_app_action",
               "put_in_folder", "undo_last_action", "improve_writing", "apply_writing", "search_web"}


def _is_quiet(call: dict, text: str) -> bool:
    name, args = call["name"], call["input"]
    if name == "app_help":
        return bool(args.get("do_it")) and text.startswith("Done")
    if name == "notes":
        return args.get("action") in ("add", "done")
    if name == "workspace":
        return args.get("action") == "open"
    return name in QUIET_TOOLS


# "Close the Finder window" is close_windows, not arrange_windows.
CLOSE_OR_MINIMIZE = re.compile(r"\b(close|minimi[sz]e)\b", re.IGNORECASE)
CLOSE_WHICH_APP = re.compile(r"\b(?:close|minimi[sz]e)\s+(?:all\s+)?(?:of\s+)?(?:the\s+|my\s+)?(.+?)\s+(?:windows?|tabs?)\b",
                             re.IGNORECASE)
CLOSE_APP = re.compile(r"^\W*(?:(?:please|can you|could you|dock)[\s,]+)*(?:close|quit)\s+(?:the\s+|my\s+)?"
                       r"([\w .-]+?)(?:\s+app)?(?:\s+(?:please|now|for me))*[\s.!?]*$", re.IGNORECASE)


def apps_match(said: str, named: str) -> bool:
    """Normalize app names for comparison."""
    norm = lambda name: re.sub(r"[^a-z0-9]", "", name.lower())
    return bool(norm(said)) and (norm(said) in norm(named) or norm(named) in norm(said))


NOT_AN_APP = {"this", "that", "these", "those", "current", "front", "other", "all", "every", "open", "the"}
# "Close/hide everything except X" and "close all windows".
CLEAR_ALL = re.compile(r"^\W*(?:(?:hey|ok(?:ay)?|so|dock|can you|could you|please)[\s,]+)*(?:close|hide|minimi[sz]e)\s+"
                       r"(?:all|every|everything)\s*(?:of\s+)?(?:the\s+|my\s+)?(?:open\s+)?(?:windows?|apps?)?"
                       r"(?:\s+(?:on|from)\s+(?:the\s+|my\s+)?(?:desktop|screen|computer|mac))?(?:\s+(?:please|now|for me))*[\s.!?]*$",
                       re.IGNORECASE)
EVERYTHING_BUT = re.compile(
    r"\b(?:close|hide|minimi[sz]e|get rid of|clear)\b.*?\b(?:all|every\w*|other|others|the rest)\b.*?"
    r"\b(?:except(?: for)?|but|besides|other than|apart from|aside from)\s+(?:the\s+|my\s+)?(.+?)"
    r"(?:\s+(?:app|apps|window|windows))?(?:,?\s+(?:please|now|for me))*[\s.!?]*$", re.IGNORECASE)
# do_app_action is only for "do it" style follow-ups.
DO_IT = re.compile(r"^\W*(ok(ay)?|yes|yeah|yep|sure|please|now|go ahead|alright)?[\s,]*(please\s+)?"
                   r"(do it|do that|click it|click that|press it|press that|yes|yeah|go ahead|sure)\b", re.IGNORECASE)
# "Check/proofread this" is writing help, not reading.
CHECK_WRITING = re.compile(
    r"^(?:(?:hey|ok(?:ay)?|so|can you|could you|would you|please|dock)[\s,]+)*"
    r"(?:check|proof\s?read|look over|go over|read over|double[- ]check|polish|correct|clean up|fix up|review)"
    r"(?:\s+(?:over|through))?\s+(?:(this|that|my|the)\s+)?"
    r"(text|writing|paragraph|sentence|essay|message|draft|reply|wording|spelling|grammar|email|bit|part|it|this)"
    r"(?:\s+(?:for|please|now|again)\b.*)?[\s.!?]*$", re.IGNORECASE)
CHECK_HOW = "check it for typos and grammar, and improve the wording a little"
# "How do I ..." goes to app_help; only explicit "google X" goes to search.
HOW_OR_WHERE = re.compile(r"^\W*(?:(?:hey|ok(?:ay)?|so|dock)[\s,]+)*(how (?:do|can|would|should) i|how to|where (?:do|can|is|are|should|to)|where's)\b",
                          re.IGNORECASE)
GET_BACK = re.compile(r"\b(recover|restore|undelete|get (?:it|that|this|them) back|bring (?:it|that|this) back|older version|previous version)\b",
                      re.IGNORECASE)
SAID_SEARCH = re.compile(r"\b(google|search|look (?:it |that )?up|online|on the web|the internet)\b", re.IGNORECASE)
# "Read/summarize this" is reading, not app_help.
READ_THIS = re.compile(r"^(?:can you |could you |please )?(read|summari[sz]e)\b(?! about)", re.IGNORECASE)

# Fix arguments where the model merged two of them with leftover markup.
LEAKED_ARGUMENT = re.compile(r'</?parameter(?:\s+name="?(\w+)"?)?\s*>')


def repair_arguments(args: dict) -> None:
    for key, value in list(args.items()):
        if isinstance(value, str) and LEAKED_ARGUMENT.search(value):
            first, *rest = LEAKED_ARGUMENT.split(value)
            args[key] = first.strip()
            for name, part in zip(rest[::2], rest[1::2]):
                if name and part.strip() and not args.get(name):
                    args[name] = part.strip()


def fix_call(call: dict, text: str, context: str = "") -> None:
    """Correct the model's tool choice in a few cases where the user's words are unambiguous."""
    repair_arguments(call["input"])
    # A plain "undo" is the app's Undo unless Dock just moved files.
    if call["name"] == "undo_last_action" and "Dock just moved files" not in context and not re.search(
            r"\b(files?|move|moved|back|downloads?|folders?)\b", text, re.IGNORECASE):
        call["name"], call["input"] = "app_help", {"question": text}
    said_folder, said_workspace = re.search(r"\bfolder\b", text, re.I), re.search(r"\bworkspace\b", text, re.I)
    if call["name"] == "workspace" and call["input"].get("action") == "open" and said_folder and not said_workspace:
        call["name"], call["input"] = "open_folder", {"name": call["input"].get("name", "")}
    elif call["name"] == "open_folder" and said_workspace and not said_folder:
        call["name"], call["input"] = "workspace", {"action": "open", "name": call["input"].get("name", "")}
    # "Yes" / "do it" right after an offer accepts it.
    offer = writing.newest_offer() if call["name"] == "do_app_action" and DO_IT.search(text) else ""
    if offer == "writing":
        call["name"], call["input"] = "apply_writing", {"where": "replace"}
    elif offer == "search":
        call["name"], call["input"] = "search_web", {"query": writing.search_offer()["query"], "go": True}
    if (call["name"] == "search_web" and not call["input"].get("go") and (HOW_OR_WHERE.search(text) or GET_BACK.search(text))
            and not SAID_SEARCH.search(text)):
        call["name"], call["input"] = "app_help", {"question": text}
    # "Can I recover it?" is about the app in front (version history).
    if (GET_BACK.search(text) and call["name"] in ("reply", "get_recap", "search_my_stuff", "get_schedule", "find_files")
            and not re.search(r"\b(files?|downloads?|folders?|emails?)\b", text, re.IGNORECASE)):
        call["name"], call["input"] = "app_help", {"question": text}
    if call["name"] == "search_web" and call["input"].get("go") and not writing.search_offer():
        call["input"]["go"] = False
    if call["name"] in ("focus_status", "reply") and re.search(r"\b(need|take|taking|want|have) a break\b", text, re.IGNORECASE):
        call["name"], call["input"] = "control_focus", {"action": "break"}
    clear_all = CLEAR_ALL.search(text.strip())
    if clear_all and call["name"] in ("app_help", "arrange_windows", "do_app_action", "reply", "close_windows"):
        if re.search(r"\bclose\b", text, re.IGNORECASE):
            call["name"], call["input"] = "close_windows", {"app": "all"}
        else:
            call["name"], call["input"] = "arrange_windows", {"layout": [], "hide_others": True}
        return
    keep = EVERYTHING_BUT.search(text.strip())
    if keep and call["name"] in ("app_help", "arrange_windows", "do_app_action", "search_web", "reply"):
        app = "" if keep.group(1).lower() in ("this", "this one", "this app", "this window", "it") else keep.group(1)
        call["name"], call["input"] = "arrange_windows", {"layout": [{"app": app, "place": "as is"}], "hide_others": True}
        return
    if call["name"] == "do_app_action" and not DO_IT.search(text):
        call["name"], call["input"] = "app_help", {"question": text}
    named = call["input"].get("app", "") or next(
        (place.get("app") for place in call["input"].get("layout", []) if place.get("app")), "")
    close_app = CLOSE_APP.search(text.strip())
    if (close_app and named and call["name"] in ("arrange_windows", "app_help")
            and apps_match(close_app.group(1), named)):
        call["name"], call["input"] = "close_windows", {"app": named, "which": "all"}
        return
    closing = re.search(r"\bclose\b.*\bwindows?\b", text, re.IGNORECASE) and not re.search(r"\btabs?\b", text, re.IGNORECASE)
    if closing and call["name"] in ("arrange_windows", "app_help", "do_app_action", "reply"):
        said = CLOSE_WHICH_APP.search(text)
        if not named and said and said.group(1).lower() not in NOT_AN_APP:
            named = said.group(1)
        which = "all" if re.search(r"\b(all|every)\b", text, re.IGNORECASE) else "front"
        call["name"], call["input"] = "close_windows", {"app": named, "which": which}
        return
    if call["name"] == "arrange_windows" and CLOSE_OR_MINIMIZE.search(text):
        named = next((place.get("app") for place in call["input"].get("layout", []) if place.get("app")), "")
        said = CLOSE_WHICH_APP.search(text)
        if not named and said and said.group(1).lower() not in NOT_AN_APP:
            named = said.group(1)
        call["name"], call["input"] = "app_help", {"question": text, "app": named}
    checking = CHECK_WRITING.search(text.strip())
    if checking and call["name"] in ("read", "app_help", "reply", "search_web", "improve_writing") and not (
            checking.group(2).lower() == "email" and (checking.group(1) or "").lower() not in ("this", "that")):
        said_how = re.search(r"\bfor\b.+", text, re.IGNORECASE)
        call["name"], call["input"] = "improve_writing", {"how": f"check it {said_how.group(0)}" if said_how else CHECK_HOW}
        return
    read = READ_THIS.search(text.strip())
    if call["name"] == "app_help" and read:
        call["name"], call["input"] = "read", {"how": "aloud" if read.group(1).lower() == "read" else "summarize"}
    if call["name"] == "app_help":
        # Decide "do it" vs "show me" from the user's own words.
        call["input"]["do_it"] = not wants_to_learn(text)


# Tools whose result needs a follow-up step.
NEEDS_FOLLOW_UP = {"find_files"}
# If the model names a found file without opening it, open it.
WANTS_OPEN = re.compile(r"\b(open|show|pull up|bring up|get me)\b", re.IGNORECASE)
FOUND_PATH = re.compile(r"\(path: (.+?)\)$", re.MULTILINE)


def _named_file(found: list[str], said: str) -> str:
    """The found path the model mentioned, else the newest."""
    lowered = said.lower()
    return next((path for path in found if Path(path).name.lower() in lowered), found[0])

HISTORY_TURNS = 6
FORGET_AFTER_SECONDS = 600
_history: list[dict] = []
_last_used = 0.0


def _tool_text(result) -> str:
    return " ".join(block.text for block in result.content if block.type == "text").strip()


def _remember(text: str, reply: str, quiet: bool = False) -> tuple[str, bool]:
    _history.extend([
        {"role": "user", "content": [{"text": text}]},
        {"role": "assistant", "content": [{"text": reply}]},
    ])
    del _history[: -HISTORY_TURNS * 2]
    return reply, quiet


async def answer(text: str, mcp_url: str, token: str, context: str = "") -> tuple[str, bool]:
    """Returns the reply and whether it's a quiet command (no speech)."""
    trace = tracing.start("voice", text)
    try:
        reply, quiet = await _answer(text, mcp_url, token, context, trace["id"])
    except Exception as e:
        tracing.finish(trace, "", error=repr(e)[:300])
        raise
    tracing.finish(trace, reply, quiet=quiet)
    return reply, quiet


async def _call_tool(mcp: Client, name: str, args: dict, **note):
    """Call one MCP tool and record it in the trace."""
    traced = tracing.step(type="tool", name=name, **note)
    started = time.perf_counter()
    result = await mcp.call_tool(name, args)
    traced.update(seconds=round(time.perf_counter() - started, 3), ok=not result.is_error)
    return result


async def _answer(text: str, mcp_url: str, token: str, context: str, trace_id: str) -> tuple[str, bool]:
    global _last_used
    if time.time() - _last_used > FORGET_AFTER_SECONDS:
        _history.clear()
    _last_used = time.time()

    # Some tools (tidy-up plans) are slow.
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}", tracing.HEADER: trace_id}, timeout=90)
    async with http, Client(streamable_http_client(mcp_url, http_client=http)) as mcp:
        listed = await mcp.list_tools()
        tools = [
            {"toolSpec": {"name": t.name, "description": t.description or "", "inputSchema": {"json": t.input_schema}}}
            for t in listed.tools
        ] + [REPLY_TOOL]
        messages = [*_history, {"role": "user", "content": [{"text": text}]}]
        found, opened = [], False

        for step in range(MAX_STEPS):
            response = await asyncio.to_thread(bedrock.converse, messages, SYSTEM, tools, 300, step == 0,
                                               bedrock.ROUTER_MODEL_ID, context, "router")
            message = response["output"]["message"]
            messages.append(message)
            calls = [block["toolUse"] for block in message["content"] if "toolUse" in block]
            for call in calls:
                before = call["name"]
                fix_call(call, text, context)
                if call["name"] != before:
                    tracing.step(type="fix", **{"from": before, "to": call["name"]})
            reply = next((c for c in calls if c["name"] == "reply"), None)
            said = bedrock.message_text(message) if response["stopReason"] != "tool_use" else (
                str(reply["input"].get("text", "")).strip() if reply else "")
            if (response["stopReason"] != "tool_use" or reply) and found and not opened and WANTS_OPEN.search(text):
                result = await _call_tool(mcp, "open_file", {"path": _named_file(found, said)}, guard=True)
                print(f"Voice -> open_file (the model only said it) -> {'error' if result.is_error else 'ok'}")
                return _remember(text, _tool_text(result), not result.is_error)
            if response["stopReason"] != "tool_use":
                return _remember(text, said)
            if reply:
                return _remember(text, said or "Okay.")
            results = []
            for call in calls:
                result = await _call_tool(mcp, call["name"], call["input"])
                print(f"Voice -> {call['name']} {call['input']} -> {'error' if result.is_error else 'ok'}")
                if call["name"] == "find_files" and not result.is_error:
                    found = FOUND_PATH.findall(_tool_text(result))
                opened = opened or (call["name"] == "open_file" and not result.is_error)
                results.append({
                    "toolResult": {
                        "toolUseId": call["toolUseId"],
                        "content": [{"text": _tool_text(result)}],
                        "status": "error" if result.is_error else "success",
                    }
                })
            # Tools that already return a spoken sentence skip the second model call.
            only = results[0]["toolResult"] if len(calls) == 1 else None
            follow_up = calls[0]["name"] in NEEDS_FOLLOW_UP
            if only and only["status"] == "success" and not follow_up:
                said = only["content"][0]["text"]
                return _remember(text, said, _is_quiet(calls[0], said))
            messages.append({"role": "user", "content": results})

    return "Sorry, I couldn't finish that.", False
