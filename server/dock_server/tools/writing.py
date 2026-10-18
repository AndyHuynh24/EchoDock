"""Writing help right where the text is, and Google when Dock isn't sure.

- improve_writing: the user selects text in any app (an email, a document,
  a chat box, a web form) and says "fix the grammar", "make this more
  professional", "make it shorter"... Claude Haiku rewrites it, and Dock
  shows the suggestion first (on the phone and the Mac, changes marked). The
  user chooses: Replace (the desktop agent puts it in place of the selection,
  no copy and paste into another chat app), Insert below (the original stays),
  or more changes ("make it shorter too" changes the suggestion again).
  apply_writing does the choice by voice. The app's own Undo (Command Z, or Ctrl+Z on Windows) undoes it.
- search_web: offers a Google search ("Search Google for …?" with a Search
  button), for "google X" / "look up X", and when Dock can't find or answer
  something. Only Search (or "yes") opens it, in a new tab of the user's
  default browser.
"""

import asyncio
import difflib
import re
import time
import urllib.parse

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import bedrock
from dock_server.hub import Hub
from dock_server.tools.computer import run_on_computer

MAX_CHARS = 8000  # longer selections: do it in parts
SUGGESTION_MINUTES = 10  # a suggestion nobody answered is dropped after this
MARK_CHANGES_ABOVE = 0.5  # mark what changed when this much stays the same, else show it plain
WRITE_SYSTEM = (
    "You edit someone's text exactly as they ask. Keep their meaning, language, voice, names, numbers, "
    "links and formatting (line breaks, lists, greetings, sign-offs) unless they ask otherwise. For a "
    "fix (grammar, spelling, typos, punctuation, capital letters), change only what's wrong. Reply with only the new "
    "text: no quotes around it, no explanation, no markdown. If you can't or won't do it, reply with only "
    "\"CANNOT: \" and one short reason."
)


REFUSAL = re.compile(r"(I can't|I cannot|I can’t|I'm sorry|I’m sorry|Sorry, I|I won't|I'm not able|I am not able)\b", re.IGNORECASE)


def google_url(query: str) -> str:
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query.strip())


def _clean(answer: str) -> str:
    text = answer.strip()
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text)  # (in case the model wrapped it anyway)
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1]
    return text


def _changes(old: str, new: str) -> int:
    """How many words changed ("libary tomorow" -> "library tomorrow" is 2)."""
    matcher = difflib.SequenceMatcher(None, old.split(), new.split())
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")


def _parts(old: str, new: str) -> list[list[str]]:
    """The suggestion with what changed marked, for the card: [kind, text]
    pieces, kind "" (the same), "del" (taken out) or "add" (put in). A rewrite
    that changes most of it is shown plain."""
    a, b = re.findall(r"\s+|\S+", old), re.findall(r"\s+|\S+", new)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if matcher.ratio() < MARK_CHANGES_ABOVE:
        return [["", new]]
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(["", "".join(a[i1:i2])])
            continue
        if tag in ("replace", "delete"):
            parts.append(["del", "".join(a[i1:i2])])
        if tag in ("replace", "insert"):
            parts.append(["add", "".join(b[j1:j2])])
    return parts


# The suggestion Dock is showing, waiting for the user's choice:
# {"pid", "app", "original", "new", "fix", "at"}, or None.
_suggestion: dict | None = None


def suggestion() -> dict | None:
    global _suggestion
    if _suggestion and time.time() - _suggestion["at"] > SUGGESTION_MINUTES * 60:
        _suggestion = None
    return _suggestion


# The Google search Dock offered: {"query", "at"}, or None.
_search: dict | None = None


def search_offer() -> dict | None:
    global _search
    if _search and time.time() - _search["at"] > SUGGESTION_MINUTES * 60:
        _search = None
    return _search


def newest_offer() -> str:
    """Which offer a plain "yes" answers: "writing", "search" or ""."""
    offers = [(o["at"], name) for name, o in (("writing", suggestion()), ("search", search_offer())) if o]
    return max(offers)[1] if offers else ""


async def offer_search(hub: Hub, query: str, why: str = "") -> None:
    """Show "Search Google for …?" with a Search button; nothing opens until the user says so."""
    global _search
    _search = {"query": query.strip(), "at": time.time()}
    await hub.push_phone("search_offer", query=query.strip(), why=why)


async def search(hub: Hub, query: str) -> str:
    global _search
    _search = None
    await run_on_computer(hub, "open_url", url=google_url(query))
    await hub.push_phone("search_done")
    await hub.push_phone("done", title=f"Searched: {query.strip()}"[:48])
    return f"I searched Google for {query.strip()} in your browser."


async def search_from_phone(hub: Hub, message: dict) -> None:
    """The search card's buttons: Search, or Not now."""
    global _search
    query = (message.get("query") or (search_offer() or {}).get("query") or "").strip()
    if not message.get("go") or not query:
        _search = None
        await hub.push_phone("search_done")
        return
    try:
        await search(hub, query)
    except ToolError as e:
        await hub.push_phone("card", title="Couldn't search", detail=str(e))


def voice_context() -> str:
    text = ""
    offered = search_offer()
    if offered:
        text += (f" Dock offered to search Google for \"{offered['query']}\": \"yes\", \"search it\" or \"go ahead\" "
                 "means search_web with go true and that query; \"no\" means reply.")
    shown = suggestion()
    if not shown:
        return text
    return text + (f" Dock is showing a suggested change to the user's text in {shown['app']}, waiting for their choice: "
            "\"use it\", \"replace it\", \"yes\" or \"looks good\" means apply_writing with replace; \"put it below\", "
            "\"add it under\" or \"keep both\" means apply_writing with below; \"no\" or \"never mind\" means apply_writing "
            "with cancel; more changes (\"make it shorter too\", \"more formal\", \"also fix the ending\") mean "
            "improve_writing, which changes the suggestion.")


async def _rewrite(how: str, text: str) -> str:
    answer = await asyncio.to_thread(bedrock.ask, f"What they asked: {how}\n\nTheir text:\n{text}", WRITE_SYSTEM,
                                     min(4000, len(text) // 2 + 400), bedrock.SMART_MODEL_ID)
    new = _clean(answer)
    if not new:
        raise ToolError("I couldn't rewrite that. Please try again.")
    # A refusal or an explanation is never offered as the user's new text.
    if new.startswith("CANNOT:"):
        raise ToolError(f"I couldn't do that: {new.removeprefix('CANNOT:').strip()}")
    if REFUSAL.match(new) and not REFUSAL.match(text.strip()):
        raise ToolError("I couldn't rewrite that the way you asked. Try saying it another way.")
    return new


async def apply(hub: Hub, where: str) -> str:
    """Do what the user chose for the suggestion: replace, below or cancel."""
    global _suggestion
    shown = suggestion()
    if not shown:
        raise ToolError("There's no suggestion waiting. Select some text and ask me to fix or change it.")
    if where == "cancel":
        _suggestion = None
        await hub.push_phone("writing_done")
        return "Okay, I left your text as it was."
    # The selection must still be the text the suggestion is for (else it would land somewhere else).
    try:
        now = await run_on_computer(hub, "selected_text", timeout=10)
    except ToolError:
        now = {"text": ""}
    if now["text"].strip() != shown["original"].strip():
        raise ToolError(f"Select the original text in {shown['app']} again, then say {'replace it' if where == 'replace' else 'put it below'}.")
    original, new = shown["original"], shown["new"].strip()
    if where == "below":
        # On its own lines under the original (which may end with a line break already).
        await run_on_computer(hub, "insert_below_selection", timeout=10, pid=shown["pid"],
                              text=(new + "\n") if original.endswith("\n") else "\n\n" + new)
        what = "Added it below"
    else:
        # (Keep the spaces or line break the selection ended with: replacing them would join lines.)
        await run_on_computer(hub, "replace_selected_text", timeout=10, pid=shown["pid"],
                              text=new + original[len(original.rstrip()):])
        changed = _changes(original, new)
        what = f"Fixed {changed} spot{'s' if changed != 1 else ''}" if shown["fix"] else "Replaced your text"
    _suggestion = None
    await hub.push_phone("writing_done")
    await hub.push_phone("done", title=f"{what} in {shown['app']}"[:48], detail=f"{hub.undo_key[0]} undoes it")
    return f"Done: {what.lower()} in {shown['app']}. {hub.undo_key[1]} undoes it."


async def from_phone(hub: Hub, message: dict) -> None:
    """A button on the suggestion card: Replace, Insert below or ×."""
    try:
        await apply(hub, message.get("where", "cancel"))
    except ToolError as e:
        await hub.push_phone("card", title="Couldn't change it", detail=str(e))


def register(mcp: MCPServer, hub: Hub) -> None:
    @mcp.tool()
    async def improve_writing(how: str = "fix the grammar and typos") -> str:
        """Fix or improve the text the user has selected, in any app (an email,
        a document, a chat box, a web form), with no copying and pasting: "fix
        the grammar", "check this for typos", "make this more professional",
        "make it shorter", "make this friendlier", "rewrite this so it's
        clearer", "translate this to Spanish". Dock shows the suggestion and the
        user chooses (apply_writing); asked again while a suggestion is showing,
        it changes the suggestion further. how: what they asked, in their words.
        Not for app features (app_help) or reading aloud (read)."""
        global _suggestion
        shown = suggestion()
        try:
            selected = await run_on_computer(hub, "selected_text", timeout=10)
        except ToolError:
            if not shown:
                raise
            selected = {"text": "", "app": shown["app"], "pid": shown["pid"]}
        text = selected["text"]
        # More changes to the suggestion showing ("make it shorter too"), or a new one for other text.
        more = bool(shown) and (not text.strip() or text.strip() == shown["original"].strip())
        if len(text) > MAX_CHARS:
            raise ToolError(f"That's a lot of text ({len(text)} characters). Select up to about {MAX_CHARS} at a time.")
        fix = bool(re.search(r"\b(fix|typo|grammar|spell|check|correct)", how, re.I))
        if more:
            original = shown["original"]
            new = await _rewrite(how, shown["new"])
            fix = fix and shown["fix"]
        else:
            original = text
            new = await _rewrite(how, text)
            if new.strip() == text.strip():
                return "It already reads well, so I left it as it is."
        _suggestion = {"pid": selected["pid"], "app": selected["app"], "original": original, "new": new.strip(),
                       "fix": fix, "at": time.time()}
        await hub.push_phone("writing", app=selected["app"], parts=_parts(original.strip(), new.strip()),
                             title="Suggested fix" if fix else "Suggested change")
        return (f"Here's my suggestion for your text in {selected['app']}: {new.strip()} "
                "Say replace it, put it below, or tell me what else to change.")

    @mcp.tool()
    async def apply_writing(where: str = "replace") -> str:
        """The user's choice for the writing suggestion Dock is showing (from
        improve_writing): where "replace" puts it in place of their selected
        text ("use it", "replace it", "yes", "looks good"), "below" adds it
        under the original and keeps both ("put it below", "insert it under"),
        "cancel" drops it ("no", "never mind")."""
        if where not in ("replace", "below", "cancel"):
            raise ToolError('where must be "replace", "below" or "cancel".')
        return await apply(hub, where)

    @mcp.tool()
    async def search_web(query: str, go: bool = False) -> str:
        """Offer a Google search, in a new tab of the user's web browser:
        "google how to cite a website in APA", "look up the UMass library
        hours", "search for cheap flights to Boston". Also use it when no other
        tool can do what the user asked and you don't know the answer, instead
        of saying you can't. Dock shows the search with a Search button first;
        go: true only when the user said yes to a search Dock offered."""
        if not query.strip():
            raise ToolError("What should I search for?")
        if go:
            return await search(hub, query)
        await offer_search(hub, query)
        return f"Want me to search Google for {query.strip()}? Tap Search, or say yes."
