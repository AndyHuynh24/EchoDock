"""Computer control tools. They work with or without a focus session."""

from typing import Literal

from mcp.server import MCPServer
from pydantic import BaseModel
from mcp.server.mcpserver.exceptions import ToolError

from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.savings import Savings

OFFLINE = "Your computer isn't connected to Dock right now. Make sure the Dock desktop agent is running."

SEARCH_TIMEOUT = 15


async def run_on_computer(hub: Hub, action: str, timeout: float = 5, **args) -> dict:
    """Run a job on the desktop agent; failures become tool errors."""
    try:
        return await hub.ask_agent(action, timeout=timeout, **args)
    except AgentOffline:
        raise ToolError(OFFLINE)
    except AgentError as e:
        raise ToolError(str(e))


Place = Literal["left", "right", "top", "bottom", "full", "center", "left third", "middle third", "right third",
                "left two thirds", "right two thirds", "top left", "top right", "bottom left", "bottom right", "as is"]


class WindowPlace(BaseModel):
    app: str = ""
    place: Place


def register(mcp: MCPServer, hub: Hub, savings: Savings) -> None:
    # Folders and apps fall back to each other ("open CS589" vs "open Calculator").
    async def folder_reply(result: dict) -> str:
        folder, place = result["folder"], result["where"]
        await hub.push_phone("toast", text=f"✓ Opened {folder}")
        await savings.add("opened")
        text = f"Opened your {folder} folder" + (f", in {place}." if place else ".")
        if result["other_matches"]:
            text += f" I also found {result['other_matches']} other folders with a similar name."
        return text

    async def app_reply(result: dict) -> str:
        await hub.push_phone("toast", text=f"✓ Opened {result['app']}")
        await savings.add("opened")
        return f"Opened {result['app']}."

    @mcp.tool()
    async def open_folder(name: str) -> str:
        """Open a folder on the user's Mac in Finder. Works for common folders
        (Downloads, Desktop, Documents, Pictures, Music, Movies, Applications,
        home) and for any other folder by name, such as "stat310" or "hackathon
        project": Dock searches the whole home folder, including iCloud Drive
        and cloud drives. Spoken names are fine: "CS 589" finds "CS589"."""
        try:
            return await folder_reply(await run_on_computer(hub, "open_folder", timeout=SEARCH_TIMEOUT, name=name))
        except ToolError as no_folder:
            try:
                return await app_reply(await run_on_computer(hub, "open_app", name=name, exact=True))
            except ToolError:
                raise no_folder

    @mcp.tool()
    async def find_files(name: str = "", kind: str = "", folder: str = "", days: int = 0) -> str:
        """Search the user's Mac for files. Every filter is optional:
        name: words from the file name or the folders it is in, e.g. "homework 3"
        or "stat310 homework";
        kind: pdf, image, video, audio, document, spreadsheet, presentation, or
        an extension like docx;
        folder: a folder to search inside, e.g. "downloads" or "stat310";
        days: only files changed in the last N calendar days (1 = today,
        2 = since yesterday, 7 = this week).
        Returns up to 8 matches, newest first, each with its path. To open one,
        call open_file with its path."""
        result = await run_on_computer(
            hub, "find_files", timeout=SEARCH_TIMEOUT, name=name, kind=kind, folder=folder, days=days
        )
        found = result["files"]
        if not found:
            if name and not kind and not days:
                try:
                    folder = await run_on_computer(hub, "find_folder", timeout=SEARCH_TIMEOUT, name=name)
                    if folder.get("folder"):
                        return (f"No files with that name, but {folder['folder']} is a folder in {folder['where']}. "
                                "If the user wanted to open it, call open_folder.")
                except ToolError:
                    pass
            return "No matching files found."
        lines = [
            f"{n}. {f['name']} in {f['where'] or 'the home folder'}, changed {f['changed']} (path: {f['path']})"
            for n, f in enumerate(found, start=1)
        ]
        header = f"Found {result['total']} matching files"
        header += f", showing the newest {len(found)}:" if result["total"] > len(found) else ":"
        if result["note"]:
            header = f"{result['note']} {header}"
        return "\n".join([header, *lines])

    @mcp.tool()
    async def open_file(path: str, show_in_finder: bool = False) -> str:
        """Open a file (or folder) on the user's Mac using its full path, usually
        a path returned by find_files. Set show_in_finder to true to show the
        file in Finder instead of opening it."""
        result = await run_on_computer(hub, "open_path", path=path, show_in_finder=show_in_finder)
        await hub.push_phone("toast", text=f"✓ Opened {result['name']}")
        await savings.add("opened")
        if show_in_finder:
            return f"Here's {result['name']} in Finder."
        return f"Opened {result['name']}."

    @mcp.tool()
    async def open_app(name: str) -> str:
        """Open an app on the user's Mac by name, for example "VS Code",
        "Chrome", "iMovie" or "Calculator". If no app has that name but a folder
        does (e.g. "open CS589"), the folder opens instead."""
        try:
            return await app_reply(await run_on_computer(hub, "open_app", name=name))
        except ToolError as no_app:
            try:
                # Exact folder names only.
                return await folder_reply(await run_on_computer(hub, "open_folder", timeout=SEARCH_TIMEOUT, name=name, close=False))
            except ToolError:
                raise no_app

    @mcp.tool()
    async def close_windows(app: str = "", which: Literal["front", "all"] = "front") -> str:
        """Close windows on the user's computer, like clicking their close button.
        app: the app's name ("" = the app in front, "all" = every app).
        which: "front" (its front window) or "all" (all its windows). Examples:
        - "close this window": app "", which front,
        - "close all the Finder windows" / "close Safari": app Finder / Safari, which all,
        - "close all windows" / "close everything on my desktop": app "all".
        Apps keep running, and a window with unsaved work asks to save first, so
        nothing is lost. Not for tabs or minimizing (app_help)."""
        result = await run_on_computer(hub, "close_windows", timeout=20, app=app, which=which)
        closed, names = result["closed"], result["apps"]
        if not closed:
            return f"There are no {app + ' ' if app and app != 'all' else ''}windows to close."
        await hub.push_phone("done", title=f"Closed {closed} window{'s' if closed != 1 else ''}",
                             detail=", ".join(names)[:80])
        await savings.add("arranged", 1)
        if app == "all":
            return f"Done: I closed {closed} window{'s' if closed != 1 else ''}."
        return f"Done: I closed {closed if closed > 1 else 'the'} {names[0]} window{'s' if closed != 1 else ''}."

    @mcp.tool()
    async def arrange_windows(layout: list[WindowPlace], screen: Literal["this", "other", "main"] = "this",
                              hide_others: bool = False) -> str:
        """Arrange windows on the user's screen. Each entry puts one app's front
        window in a place; app "" means the app in front. Apps that aren't open
        yet are opened. Examples:
        - "put Chrome on the left and Notes on the right" (or "split screen with
          Chrome and Notes"): [{app Chrome, place left}, {app Notes, place right}],
        - "make this full screen" / "make it bigger": [{app "", place full}],
        - "move this to my other screen": [{app "", place full}], screen "other",
        - "just Chrome, hide the rest": [{app Chrome, place full}], hide_others true,
        - "close everything except VS Code": [{app VS Code, place "as is"}], hide_others true
          (the other apps are hidden, never quit, so nothing unsaved is lost),
        - "hide everything" / "clear my screen": [] with hide_others true (everything is hidden).
        Closing or minimizing a window isn't arranging it."""
        result = await run_on_computer(hub, "arrange_windows", timeout=20,
                                       layout=[item.model_dump() for item in layout], screen=screen, hide_others=hide_others)
        done, problems = result["arranged"], result["problems"]
        if "cleared" in result:
            await hub.push_phone("done", title="Desktop cleared", detail="Your apps are hidden, not closed")
            await savings.add("arranged", 1)
            return "Done: I hid all your windows. Nothing was closed, so nothing is lost."
        kept = [d["app"] for d in done if d["place"] == "as is"]
        if kept and hide_others and len(kept) == len(done):
            await hub.push_phone("done", title=f"Only {', '.join(kept)} now"[:48], detail="The other apps are hidden, not closed")
            await savings.add("arranged", len(done))
            return f"Done: I hid everything except {' and '.join(kept)}."
        if done:
            await hub.push_phone("toast", text="✓ " + ", ".join(f"{d['app']} {d['place']}" for d in done))
            await savings.add("arranged", len(done))
        if screen == "other" and result["screens"] < 2:
            problems.append("There's only one screen.")
        text = ("Done: " + ", ".join(f"{d['app']} on the {d['place']}" if d["place"] not in ("full", "center")
                                     else f"{d['app']} {'filling the screen' if d['place'] == 'full' else 'in the middle'}"
                                     for d in done) + ".") if done else "I didn't move any windows."
        if hide_others and done:
            text += " I hid the other apps."
        if problems:
            text += " " + " ".join(problems)
        return text
