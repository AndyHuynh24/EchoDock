"""Read it to me / summarize: the selected text, the open document, or a file."""

import asyncio
from typing import Literal

from mcp.server import MCPServer

from dock_server import bedrock
from dock_server.hub import Hub
from dock_server.tools.computer import run_on_computer

SUMMARY_SYSTEM = (
    "Summarize the text for someone listening, not reading: 3 or 4 short, clear "
    "sentences covering the main point and the most important details. If it is an "
    "assignment, say what is being asked and any due date. No markdown, lists or emojis."
)

# The phone reads this much at most; longer texts get a note.
MAX_READ_CHARS = 4000


def register(mcp: MCPServer, hub: Hub) -> None:
    @mcp.tool()
    async def read(how: Literal["summarize", "aloud"] = "summarize", path: str = "") -> str:
        """The text the user selected, or the document open in the front window
        (PDF, Word, text...), or a specific file (pass its path, e.g. one found
        with find_files):
        - "summarize": a short spoken summary ("summarize this"),
        - "aloud": read it out loud ("read this to me", "read it to me")."""
        found = await run_on_computer(hub, "read_text", timeout=20, path=path)
        if how == "summarize":
            summary = await asyncio.to_thread(bedrock.ask, found["text"], SUMMARY_SYSTEM, 400)
            await hub.push_phone("card", title=f"Summary of {found['title']}", detail=summary)
            return summary
        text = found["text"][:MAX_READ_CHARS]
        await hub.push_phone("read", title=found["title"], text=text)
        if len(found["text"]) > MAX_READ_CHARS:
            return f"Reading the start of {found['title']}. It's long, so you could ask me to summarize it instead."
        return f"Reading {found['title']}."
