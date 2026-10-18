"""App-aware help: "where's the split tool?" and "do it".

1. The desktop agent reads every menu item of the app in front.
2. We look for the item: first a plain keyword match, and if that doesn't
   give exactly one answer, Claude Haiku on Bedrock picks from the list.
   Not in the menus? Then the window's own buttons (toolbar icons and other
   named controls, read the same way), and last, Dock looks: one screenshot
   of just that window, Claude Haiku says roughly where the control is, and
   a sharp close-up of that area pins it down (two looks, about $0.005).
   "Do it" then presses that button or clicks that spot.
   Web search for items that aren't in the menus (e.g. Chrome's Translate,
   which is only a button) is turned off for now: set DOCK_WEB_SEARCH=on to
   use it. It costs about $0.03 per search, so it only runs when the menus
   don't have the answer.
3. We say where it is and its shortcut, show it on the phone, and the agent
   opens the menu and points at the item on screen.
4. "Do it" clicks that same menu item.
"""

import asyncio
import base64
import json
import os
import re
from datetime import date

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import bedrock
from dock_server.hub import Hub
from dock_server.menu_words import display_name as _name
from dock_server.menu_words import is_risky
from dock_server.savings import Savings
from dock_server.state import State
from dock_server.tools.computer import run_on_computer
from dock_server.tools.writing import offer_search

STOP_WORDS = {
    "a", "an", "the", "is", "are", "s", "where", "wheres", "what", "how", "do", "does", "i",
    "can", "find", "tool", "button", "option", "command", "menu", "feature", "thing", "to",
    "in", "my", "me", "this", "that", "it", "of", "for", "show", "use",
}

PICK_SYSTEM = (
    "You match what a user asks for to one menu item of a Mac app. Think about what the user "
    "wants to happen, not about shared words: in an editor, \"split screen\" or \"two files side "
    "by side\" means splitting the editor (Split Right, Split Editor), not Full Screen; \"make the "
    "text bigger\" means Zoom In or Bigger. Only pick an item that does what they asked, not one "
    "that is merely related; if none does, answer 0 (Dock then looks it up on the web).\n"
    'Reply with only JSON: {"why": "a few words", "item": <number>}'
)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower().replace("'", "")))


def keyword_match(question: str, items: list[dict]) -> dict | None:
    """The single item whose menu path contains every important word of the
    question, with at least one in the item's own name ("programmer view"
    matches View > Programmer)."""
    wanted = _words(question) - STOP_WORDS
    if not wanted:
        return None
    matches = [
        item for item in items
        if wanted <= _words(" ".join(item["path"])) and wanted & _words(item["path"][-1])
    ]
    if len(matches) > 1:
        # "minimize this window": Minimize, not Minimize All (its own name has a word not asked for).
        matches = [item for item in matches if _words(item["path"][-1]) - STOP_WORDS <= wanted]
    return matches[0] if len(matches) == 1 else None


def bedrock_match(question: str, app: str, items: list[dict]) -> dict | None:
    items = [item for item in items if item["path"][0] not in SKIP_MENUS]
    lines = [
        f"{n}. {' > '.join(item['path'])}" + (f" ({item['shortcut']})" if item["shortcut"] else "")
        for n, item in enumerate(items, start=1)
    ]
    prompt = f"App: {app}\nQuestion: {question}\n\nMenu items:\n" + "\n".join(lines)
    # Claude Haiku: in our tests Nova Lite often picked a related item instead of the
    # right one ("open the terminal" -> Split Terminal). About $0.005 per question.
    answer = bedrock.ask(prompt, PICK_SYSTEM, 80, bedrock.SMART_MODEL_ID)
    number = re.search(r'"item"\s*:\s*(\d+)', answer) or re.search(r"\d+", answer)
    n = int(number.group(1) if number.groups() else number.group()) if number else 0
    return items[n - 1] if 1 <= n <= len(items) else None


WEB_SEARCH = os.environ.get("DOCK_WEB_SEARCH", "").lower() == "on"  # off for now
WEB_SYSTEM = (
    "You are a voice assistant helping someone use a Mac app right now. Look up how to do what they "
    "ask in that app, preferring the app maker's official help pages. Answer in at most two short "
    "spoken sentences that say exactly where to click or what to press. No lists, no markdown, no links."
)
# App names as macOS shows them, and what to call them in a web search.
SEARCH_NAMES = {"Code": "Visual Studio Code", "Chrome": "Google Chrome"}
# History and bookmarks are the user's own pages, not features: leave them out.
# (The Window menu stays: it has Minimize, Zoom and Move to…, besides the list of windows.)
SKIP_MENUS = {"History", "Bookmarks", "Favorites", "Help"}


def web_answer(question: str, app: str) -> tuple[str, str]:
    """How to do it, from the web. Returns the spoken answer and its source's site."""
    name = SEARCH_NAMES.get(app, app)
    answer, sources = bedrock.ask_web(f"App: {name} on macOS\nQuestion: {question}", WEB_SYSTEM)
    site = re.sub(r"^https?://(www\.)?", "", sources[0]).split("/")[0] if sources else ""
    return answer, site


VISION_SYSTEM = (
    "You see a screenshot of one window of a Mac app, and a question from its user. Find the control "
    "they need to click for it: a button, icon, tab, field or link that is visible in the screenshot. "
    "Only answer if you can actually see it; never guess a menu.\n"
    'Reply with only JSON: {"found": true, "name": "short name of the control", '
    '"where": "a few words, like top right of the toolbar", "box": [left, top, right, bottom]} '
    'with the box in pixels of this image, or {"found": false}.'
)
ZOOM = (480, 300)  # the close-up around the first guess, in screen points
# VS Code puts shortcuts in names: "Toggle Panel (⌘J)", or "Toggle Panel (Ctrl+J)" on Windows.
SHORTCUT_IN_NAME = re.compile(r"\s*\(((?:[⌃⌥⇧⌘]|(?:Ctrl|Alt|Shift|Win)\+)[^)]*)\)")
KEY_WORDS = {"⌃": "Control ", "⌥": "Option ", "⇧": "Shift ", "⌘": "Command "}
WINDOWS_KEY_WORDS = {"ctrl": "Control", "alt": "Alt", "shift": "Shift", "win": "Windows", "del": "Delete", "esc": "Escape", "+": "Plus"}


# Questions get the arrow ("how do I knit this?", "where's export?", "show me how
# to split the screen"); anything else is a command and Dock just does it
# ("knit the document", "undo", "can you split the screen").
TEACH_ME = re.compile(r"^(how|where|what|which|is there|are there|show me|teach me|explain|find)\b|show me how|where (is|are|do)",
                      re.IGNORECASE)


def wants_to_learn(question: str) -> bool:
    return bool(TEACH_ME.search(question.strip().lower().replace("where's", "where is").replace("what's", "what is")))


def spoken_keys(shortcut: str) -> str:
    if re.match(r"(Ctrl|Alt|Shift|Win)\+", shortcut):  # Windows: "Ctrl+Shift+J" -> "Control Shift J"
        return " ".join(WINDOWS_KEY_WORDS.get(k.lower(), k) for k in re.split(r"\+(?=.)", shortcut))
    return "".join(KEY_WORDS.get(c, c) for c in shortcut).replace("  ", " ").strip()


def control_items(controls: list[dict]) -> list[dict]:
    """The window's controls in the same shape as menu items, so the same matching works."""
    items = []
    for control in controls:
        found = SHORTCUT_IN_NAME.search(control["name"])
        shortcut = found.group(1).split()[0] if found else ""
        name = SHORTCUT_IN_NAME.sub("", control["name"]).split(" - ")[0].strip()
        if name:
            items.append({"path": [control["where"], name], "shortcut": shortcut, "shortcut_spoken": spoken_keys(shortcut),
                          "enabled": control["enabled"], "number": control["number"], "role": control["role"]})
    return items


def vision_find(question: str, app: str, shot: dict) -> dict | None:
    """Ask Claude Haiku where the control is in the window screenshot. Returns
    {"name", "where", "rect"} with rect in screen points, or None."""
    image = base64.b64decode(shot["image"])
    prompt = f"App: {app}\nQuestion: {question}\nThe image is {shot['width']} x {shot['height']} pixels."
    response = bedrock.converse(
        [{"role": "user", "content": [{"image": {"format": "png", "source": {"bytes": image}}}, {"text": prompt}]}],
        VISION_SYSTEM, max_tokens=150, model=bedrock.SMART_MODEL_ID)
    answer = bedrock.message_text(response["output"]["message"])
    match = re.search(r"\{.*\}", answer, re.DOTALL)
    try:
        reply = json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        return None
    box = reply.get("box")
    if not reply.get("found") or not (isinstance(box, list) and len(box) == 4):
        return None
    # From screenshot pixels to screen points.
    x0, y0, width, height = shot["bounds"]
    sx, sy = width / shot["width"], height / shot["height"]
    left, top, right, bottom = (float(v) for v in box)
    rect = [x0 + left * sx, y0 + top * sy, max(8.0, (right - left) * sx), max(8.0, (bottom - top) * sy)]
    return {"name": str(reply.get("name") or "that control")[:60], "where": str(reply.get("where") or "")[:80], "rect": rect}


# Answers are short: they're spoken, and the arrow on screen and the card on the
# phone already show where it is (and that "do it" clicks it).
DO_IT_HINT = "Say “do it” to click it"


def spoken_answer(item: dict) -> str:
    path = [_name(title) for title in item["path"]]
    if len(path) == 2:
        text = f"{path[1]} is in the {path[0]} menu."
    else:
        text = f"{path[-1]} is in {', then '.join(path[:-1])}."
    if item["shortcut_spoken"]:
        text += f" Or press {item['shortcut_spoken']}."
    if not item["enabled"]:
        text += " It's greyed out right now."
    return text


def done_text(name: str, shortcut_spoken: str = "") -> str:
    # (Dock's own voice stays quiet for commands and plays a sound; other
    # assistants calling this tool, like Alexa+, say this.)
    return f"Done: {name}." + (f" Next time, press {shortcut_spoken}." if shortcut_spoken else "")


def register(mcp: MCPServer, hub: Hub, state: State, savings: Savings) -> None:
    last_suggestion = state.last_suggestion
    times_asked = state.times_asked

    @mcp.tool()
    async def app_help(question: str, do_it: bool | None = None, app: str = "") -> str:
        """Answer where a specific feature, command or button is in the app the
        user is using right now on their computer, for example "where's the
        split tool?" or "how do I export?". Says which menu it is in and its
        keyboard shortcut, points at it on screen, and shows it on the phone.
        Pass the user's own words. app: only if the user named an app ("close the
        Finder window" -> Finder); Dock brings it to the front first. A command ("knit the document", "undo",
        "split the screen") is done right away; a question ("how do I knit
        this?", "where's export?", "show me how") gets the arrow on screen and
        the shortcut, so the user can learn it. do_it true/false overrides that.
        Not for: reading or summarizing text (read),
        greetings, or questions about what Dock itself can do."""
        if do_it is None:
            do_it = not wants_to_learn(question)
        if app.strip():
            await run_on_computer(hub, "bring_app_forward", name=app)
        front = await run_on_computer(hub, "app_menus")
        app, items = front["app"], front["items"]  # (the app now in front)
        item = keyword_match(question, items)
        if item is None:
            item = await asyncio.to_thread(bedrock_match, question, app, items)
        if item is None:
            # Not in the menus: the window's own buttons, then a look at the window.
            answer = await find_on_screen(question, app, front["pid"], do_it)
            if answer:
                return answer
        if item is None and not WEB_SEARCH:
            # Not sure: offer a Google search instead of a dead end (free; the user taps Search).
            await offer_search(hub, f"{SEARCH_NAMES.get(app, app)} {question}", why=f"Not in the {app} menus")
            return f"I couldn't find that in {app}. Want me to search Google for it?"
        if item is None:
            # Not in the menus: ask the web.
            try:
                answer, site = await asyncio.to_thread(web_answer, question, app)
            except Exception as e:
                print(f"Web search failed: {e!r}")
                raise ToolError(f"I couldn't find that in the {app} menus.")
            print(f"Web answer for {question!r} in {app} (from {site or 'the web'})")
            await hub.push_phone("card", title=question[:1].upper() + question[1:], detail=f"{answer}\n\n{app} · from {site or 'the web'}")
            await savings.add("found")
            return f"It's not in the {app} menus, but here's what I found online: {answer}"

        last_suggestion.clear()
        last_suggestion.update(app=app, pid=front["pid"], path=item["path"])
        name = _name(item["path"][-1])
        fresh = await run_on_computer(hub, "menu_item_enabled", pid=front["pid"], path=item["path"])
        if fresh["enabled"] is not None:
            item = dict(item, enabled=fresh["enabled"])
        will_do = do_it and item["enabled"] and not is_risky(name, question)
        if not will_do:
            # Teaching: one card (the item, its menu and shortcut) and an arrow
            # on screen. (A problem with the arrow isn't an error.)
            menu = " › ".join(_name(title) for title in item["path"][:-1])
            await hub.push_phone("card", title=name, shortcut=item["shortcut"],
                                 detail=f"{menu} menu · " + (DO_IT_HINT if item["enabled"] else "greyed out right now"))
            label = f"{name}   {item['shortcut']}".strip()
            try:
                await run_on_computer(hub, "highlight_menu", pid=front["pid"], path=item["path"], label=label)
            except ToolError:
                pass
        text = spoken_answer(item)

        state.questions.append((date.today(), app, name))
        key = (app, tuple(item["path"]))
        if item["shortcut"]:  # (for the focus break's flashcards)
            state.shortcuts_seen[key] = {"app": app, "name": name, "shortcut": item["shortcut"], "path": list(item["path"])}
        await savings.add("found")
        times_asked[key] = times_asked.get(key, 0) + 1
        if will_do:
            await run_on_computer(hub, "press_menu", pid=front["pid"], path=item["path"])
            await hub.push_phone("done", title=name, shortcut=item["shortcut"])
            await savings.add("clicked")
            return done_text(name, item["shortcut_spoken"])
        return text

    async def find_on_screen(question: str, app: str, pid: int, do_it: bool) -> str | None:
        """Find it among the window's named buttons, or else by looking at a
        screenshot of the window. Returns the spoken answer, or None."""
        try:
            seen = await run_on_computer(hub, "window_controls", timeout=8)
        except ToolError:
            seen = {"controls": []}
        controls = control_items(seen["controls"])
        item = keyword_match(question, controls) if controls else None
        if item is None and controls:
            item = await asyncio.to_thread(bedrock_match, question, app, controls)
        if item is not None:
            name, toolbar = item["path"][-1], item["path"][0] == "toolbar"
            last_suggestion.clear()
            last_suggestion.update(app=app, pid=pid, control=item["number"], name=name)
            await savings.add("found")
            if do_it and item["enabled"] and not is_risky(name, question):
                await run_on_computer(hub, "press_control", pid=pid, number=item["number"])
                await hub.push_phone("done", title=name, shortcut=item["shortcut"])
                await savings.add("clicked")
                return done_text(name, item["shortcut_spoken"])
            await hub.push_phone("card", title=name, shortcut=item["shortcut"],
                                 detail=("In the toolbar · " if toolbar else "") + DO_IT_HINT)
            try:
                await run_on_computer(hub, "highlight_control", number=item["number"], label=f"{name}   {item['shortcut']}".strip())
            except ToolError:
                pass
            keys = f" Or press {item['shortcut_spoken']}." if item["shortcut_spoken"] else ""
            return f"It's the {name} {item['role'].lower()}{' in the toolbar' if toolbar else ''}.{keys}"

        # Last: look at the window.
        try:
            shot = await run_on_computer(hub, "window_screenshot", timeout=15)
        except ToolError as e:
            if "Screen Recording" in str(e):
                return f"It's not in {app}'s menus or its labelled buttons. {e}"
            return None
        try:
            spot = await asyncio.to_thread(vision_find, question, app, shot)
        except Exception as e:
            print(f"Couldn't look at the screen: {e!r}")
            return None
        if spot is None:
            print(f"Looked at the {app} window for {question!r}: not found")
            return None
        # Small icons are easy to miss by a few pixels in the shrunk screenshot,
        # so take a sharp close-up around the first guess and look again.
        x, y, w, h = spot["rect"]
        try:
            zoom = await run_on_computer(hub, "screen_region", timeout=10,
                                         rect=[x + w / 2 - ZOOM[0] / 2, y + h / 2 - ZOOM[1] / 2, *ZOOM])
            closer = await asyncio.to_thread(vision_find, question, app, zoom)
            if closer:
                spot["rect"] = closer["rect"]
        except Exception as e:
            print(f"Couldn't take a closer look: {e!r}")
        print(f"Looked at the {app} window for {question!r}: {spot}")
        name, where = spot["name"], f", {spot['where']}" if spot["where"] else ""
        x, y, w, h = spot["rect"]
        last_suggestion.clear()
        last_suggestion.update(app=app, pid=pid, spot=[x + w / 2, y + h / 2], name=name)
        await savings.add("found")
        # Found by looking, it's a good guess, not a sure thing: Dock circles it and
        # only clicks when the user says "do it" (never by itself, even for a command).
        await hub.push_phone("card", title=name, detail=f"Found by looking at the window · {DO_IT_HINT}")
        await run_on_computer(hub, "highlight_spot", rect=spot["rect"], label=f"{name}?")
        return f"I think it's the {name}{where}." + (" Say do it and I'll click it." if do_it else "")

    @mcp.tool()
    async def do_app_action() -> str:
        """Click the menu item Dock just pointed to. Only for "do it", "do that",
        "click it" or "yes" right after Dock pointed at something. If the user
        names a feature ("split screen", "export"), call app_help instead."""
        if not last_suggestion:
            raise ToolError("I haven't pointed to anything yet. Ask me where something is first.")
        name = last_suggestion.get("name") or _name(last_suggestion["path"][-1])
        if is_risky(name):
            raise ToolError(f"To be safe, I won't click {name} by voice. Please click it yourself.")
        if "control" in last_suggestion:  # a button in the window
            await run_on_computer(hub, "press_control", pid=last_suggestion["pid"], number=last_suggestion["control"])
        elif "spot" in last_suggestion:  # a spot Dock found by looking
            x, y = last_suggestion["spot"]
            await run_on_computer(hub, "click_spot", pid=last_suggestion["pid"], x=x, y=y)
        else:
            await run_on_computer(hub, "press_menu", pid=last_suggestion["pid"], path=last_suggestion["path"])
        await hub.push_phone("done", title=name)
        await savings.add("clicked")
        return done_text(name)
