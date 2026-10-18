"""Simulated Alexa+: the phone sends what the user said (or typed), a Bedrock
model picks Dock's MCP tools, and we call them through our own MCP endpoint
over Streamable HTTP, the same way Alexa+ would. The phone shows or speaks
the reply.

The model may call several tools in a row for bigger tasks, e.g. find_files
and then open_file. The last few exchanges are remembered so follow-ups like
"open the second one" work."""

import asyncio
import re
import time
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from dock_server import bedrock
from dock_server.tools import writing
from dock_server.tools.app_help import wants_to_learn

SYSTEM = (
    "You are Dock, a voice assistant on the user's desk, like Alexa. You control "
    "their Mac and help them inside the app they are using, by calling the tools. "
    "You can only do things on the computer by calling tools, so call the tool every "
    "time, even if you did the same thing earlier in the conversation. Never say you "
    "opened, saved, moved, read or clicked something unless a tool did it in this turn. "
    "Never say you can't find something before searching for it. "
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
    "on the AWS console is app_help, which looks at the page. But \"read this to me\" or \"summarize this\" means read, "
    "never app_help. "
    "Never move files unless the user has clearly agreed: after suggest_folders with "
    "all_downloads, tell them the suggestions briefly (how many, and a couple of examples) "
    "and ask any questions, then call put_in_folder only when they say yes or tell you "
    "where things go. "
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

# The model must call a tool on its first step, so it can't just claim it did
# something. When no Dock tool fits (small talk, a question back to the user),
# it calls this "reply" tool instead, which we handle here.
REPLY_TOOL = {
    "toolSpec": {
        "name": "reply",
        "description": "Answer the user directly when no other tool fits: greetings and small "
                       "talk, questions about what Dock can do, or asking the user a clarifying "
                       "question.",
        "inputSchema": {"json": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    }
}

# Commands that just happen: when one of these worked, Dock doesn't talk. The
# phone and the Mac show a ✓ and play a short sound instead. (app_help counts
# when it did the command instead of showing where it is.)
QUIET_TOOLS = {"open_folder", "open_app", "open_file", "arrange_windows", "do_app_action",
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


# "Close the Finder window" is the app's Close Window command, not arranging
# windows (the model sometimes picks arrange_windows for it).
CLOSE_OR_MINIMIZE = re.compile(r"\b(close|minimi[sz]e)\b", re.IGNORECASE)
# ...and the app it names: "close all fighter windows" -> "fighter" (Dock's agent
# matches that loosely to the open apps: Finder).
CLOSE_WHICH_APP = re.compile(r"\b(?:close|minimi[sz]e)\s+(?:all\s+)?(?:of\s+)?(?:the\s+|my\s+)?(.+?)\s+(?:windows?|tabs?)\b",
                             re.IGNORECASE)
NOT_AN_APP = {"this", "that", "these", "those", "current", "front", "other", "all", "every", "open", "the"}
# "Close all windows except VS Code" / "hide everything but Chrome": keep that app, hide
# the others (hidden, never quit: nothing unsaved is lost).
EVERYTHING_BUT = re.compile(
    r"\b(?:close|hide|minimi[sz]e|get rid of|clear)\b.*?\b(?:all|every\w*|other|others|the rest)\b.*?"
    r"\b(?:except(?: for)?|but|besides|other than|apart from|aside from)\s+(?:the\s+|my\s+)?(.+?)"
    r"(?:\s+(?:app|apps|window|windows))?(?:,?\s+(?:please|now|for me))*[\s.!?]*$", re.IGNORECASE)
# do_app_action clicks what Dock last pointed at, so it's only for "do it" and
# the like; the model sometimes calls it for "close the TextEdit window".
DO_IT = re.compile(r"^\W*(ok(ay)?|yes|yeah|yep|sure|please|now|go ahead|alright)?[\s,]*(please\s+)?"
                   r"(do it|do that|click it|click that|press it|press that|yes|yeah|go ahead|sure)\b", re.IGNORECASE)
# "Check this text" / "proofread this" is writing help (typos, grammar, wording),
# which the model sometimes sends to read as if it meant "summarize". "Check my
# email" isn't, so an email only counts as "this email".
CHECK_WRITING = re.compile(
    r"^(?:(?:hey|ok(?:ay)?|so|can you|could you|would you|please|dock)[\s,]+)*"
    r"(?:check|proof\s?read|look over|go over|read over|double[- ]check|polish|correct|clean up|fix up|review)"
    r"(?:\s+(?:over|through))?\s+(?:(this|that|my|the)\s+)?"
    r"(text|writing|paragraph|sentence|essay|message|draft|reply|wording|spelling|grammar|email|bit|part|it|this)"
    r"(?:\s+(?:for|please|now|again)\b.*)?[\s.!?]*$", re.IGNORECASE)
CHECK_HOW = "check it for typos and grammar, and improve the wording a little"
# "How do I check my costs?" while on a website (the AWS console in Safari) is about
# what's on screen: app_help looks at the menus, the page's buttons and then the
# screen, and still offers Google when none of that has it. Only "google X" /
# "look up X" goes straight to the search offer.
HOW_OR_WHERE = re.compile(r"^\W*(?:(?:hey|ok(?:ay)?|so|dock)[\s,]+)*(how (?:do|can|would|should) i|how to|where (?:do|can|is|are|should|to)|where's)\b",
                          re.IGNORECASE)
SAID_SEARCH = re.compile(r"\b(google|search|look (?:it |that )?up|online|on the web|the internet)\b", re.IGNORECASE)
# Same for "read this to me" / "summarize this", which the model sometimes sends
# to app_help as if reading were a feature of the app.
READ_THIS = re.compile(r"^(?:can you |could you |please )?(read|summari[sz]e)\b(?! about)", re.IGNORECASE)

def fix_call(call: dict, text: str, context: str = "") -> None:
    """Correct the model's tool choice where the user's own words are clear, in
    place. (The model gets these few wrong now and then, and rewording its
    instructions to fix one tends to break another.) context: the facts the
    model was given (see main.py)."""
    # A plain "undo" is the app's own Undo, unless Dock has just moved files.
    if call["name"] == "undo_last_action" and "Dock just moved files" not in context and not re.search(
            r"\b(files?|move|moved|back|downloads?|folders?)\b", text, re.IGNORECASE):
        call["name"], call["input"] = "app_help", {"question": text}
    # "cs589 folder" is the folder even when a workspace has the same name (and the other way round).
    said_folder, said_workspace = re.search(r"\bfolder\b", text, re.I), re.search(r"\bworkspace\b", text, re.I)
    if call["name"] == "workspace" and call["input"].get("action") == "open" and said_folder and not said_workspace:
        call["name"], call["input"] = "open_folder", {"name": call["input"].get("name", "")}
    elif call["name"] == "open_folder" and said_workspace and not said_folder:
        call["name"], call["input"] = "workspace", {"action": "open", "name": call["input"].get("name", "")}
    # "Yes" / "do it" right after Dock offered something (a writing suggestion, a Google search): that.
    offer = writing.newest_offer() if call["name"] == "do_app_action" and DO_IT.search(text) else ""
    if offer == "writing":
        call["name"], call["input"] = "apply_writing", {"where": "replace"}
    elif offer == "search":
        call["name"], call["input"] = "search_web", {"query": writing.search_offer()["query"], "go": True}
    if call["name"] == "search_web" and not call["input"].get("go") and HOW_OR_WHERE.search(text) and not SAID_SEARCH.search(text):
        call["name"], call["input"] = "app_help", {"question": text}
    # Opening a search is only for a yes to Dock's offer: otherwise offer it first.
    if call["name"] == "search_web" and call["input"].get("go") and not writing.search_offer():
        call["input"]["go"] = False
    keep = EVERYTHING_BUT.search(text.strip())
    if keep and call["name"] in ("app_help", "arrange_windows", "do_app_action", "search_web", "reply"):
        app = "" if keep.group(1).lower() in ("this", "this one", "this app", "this window", "it") else keep.group(1)
        call["name"], call["input"] = "arrange_windows", {"layout": [{"app": app, "place": "as is"}], "hide_others": True}
        return
    if call["name"] == "do_app_action" and not DO_IT.search(text):
        call["name"], call["input"] = "app_help", {"question": text}
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
        # Decide "do it" or "show me" from the user's own words: the model
        # sometimes rewrites "split screen" as "how do I split the screen".
        call["input"]["do_it"] = not wants_to_learn(text)


# Tools whose answer needs another step (the model reads the list and acts on it).
NEEDS_FOLLOW_UP = {"find_files"}  # (and suggest_folders for the whole Downloads folder, see below)
# "Open the stat525 file from yesterday": find_files, then open_file. Sometimes the
# model just says "I opened Andy_HW4.Rmd" after find_files without opening it, so
# Dock opens the file it named (or the newest match) itself.
WANTS_OPEN = re.compile(r"\b(open|show|pull up|bring up|get me)\b", re.IGNORECASE)
FOUND_PATH = re.compile(r"\(path: (.+?)\)$", re.MULTILINE)


def _named_file(found: list[str], said: str) -> str:
    """The found path whose file name the model mentioned, else the newest one."""
    lowered = said.lower()
    return next((path for path in found if Path(path).name.lower() in lowered), found[0])

# Recent conversation, as plain user/assistant text turns.
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
    """Dock's reply, and whether it was a command that just happened (quiet:
    show a ✓ and play a sound instead of speaking)."""
    global _last_used
    if time.time() - _last_used > FORGET_AFTER_SECONDS:
        _history.clear()
    _last_used = time.time()

    # Some tools take a while (a tidy-up plan reads many files), so allow up to 90 s.
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=90)
    async with http, Client(streamable_http_client(mcp_url, http_client=http)) as mcp:
        listed = await mcp.list_tools()
        tools = [
            {"toolSpec": {"name": t.name, "description": t.description or "", "inputSchema": {"json": t.input_schema}}}
            for t in listed.tools
        ] + [REPLY_TOOL]
        messages = [*_history, {"role": "user", "content": [{"text": text}]}]
        found, opened = [], False  # (files find_files listed in this request; whether one was opened)

        for step in range(MAX_STEPS):
            response = await asyncio.to_thread(bedrock.converse, messages, SYSTEM, tools, 300, step == 0,
                                               bedrock.ROUTER_MODEL_ID, context)
            message = response["output"]["message"]
            messages.append(message)
            calls = [block["toolUse"] for block in message["content"] if "toolUse" in block]
            for call in calls:
                fix_call(call, text, context)
            reply = next((c for c in calls if c["name"] == "reply"), None)
            said = bedrock.message_text(message) if response["stopReason"] != "tool_use" else (
                str(reply["input"].get("text", "")).strip() if reply else "")
            if (response["stopReason"] != "tool_use" or reply) and found and not opened and WANTS_OPEN.search(text):
                result = await mcp.call_tool("open_file", {"path": _named_file(found, said)})
                print(f"Voice -> open_file (the model only said it) -> {'error' if result.is_error else 'ok'}")
                return _remember(text, _tool_text(result), not result.is_error)
            if response["stopReason"] != "tool_use":
                return _remember(text, said)
            if reply:
                return _remember(text, said or "Okay.")
            results = []
            for call in calls:
                result = await mcp.call_tool(call["name"], call["input"])
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
            # Most tools already reply in a finished spoken sentence. When one such
            # tool worked, say its answer directly and skip another model call.
            only = results[0]["toolResult"] if len(calls) == 1 else None
            follow_up = calls[0]["name"] in NEEDS_FOLLOW_UP or calls[0]["input"].get("all_downloads")
            if only and only["status"] == "success" and not follow_up:
                said = only["content"][0]["text"]
                return _remember(text, said, _is_quiet(calls[0], said))
            messages.append({"role": "user", "content": results})

    return "Sorry, I couldn't finish that.", False
