"""Saved workspaces: apps, documents, tabs and window positions."""

from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server.hub import Hub
from dock_server.savings import Savings
from dock_server.tools.computer import run_on_computer


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def register(mcp: MCPServer, hub: Hub, savings: Savings) -> None:
    @mcp.tool()
    async def workspace(action: Literal["save", "open", "list"], name: str = "") -> str:
        """The user's saved workspaces (the apps, their open documents,
        Chrome/Safari tabs, Finder folders and where each window is):
        - "save": remember what is open right now under a name ("remember this
          workspace as Study", "save these windows as Hackathon"),
        - "open": bring a saved one back, windows and all ("open my Study workspace"),
        - "list": say which ones exist."""
        if action == "list":
            names = (await run_on_computer(hub, "list_workspaces"))["names"]
            if not names:
                return "You don't have any saved workspaces yet. Say remember this workspace as, and a name."
            return f"Your workspaces are {_join(names)}."
        if not name.strip():
            raise ToolError("Which workspace? Give it a name.")
        if action == "save":
            result = await run_on_computer(hub, "save_workspace", timeout=20, name=name)
            extras = []
            if result["documents"]:
                extras.append(f"{result['documents']} documents")
            if result["tabs"]:
                extras.append(f"{result['tabs']} browser tabs")
            await hub.push_phone("card", title=f"Saved workspace: {name}", detail=", ".join(result["apps"]))
            text = f"Saved your {name} workspace with {_join(result['apps'])}"
            return text + (f", including {_join(extras)}." if extras else ".")
        result = await run_on_computer(hub, "open_workspace", timeout=30, name=name)
        await hub.push_phone("toast", text=f"✓ Opened {result['name']}")
        await savings.add("workspace_app", len(result["apps"]))
        return f"Your {result['name']} workspace is ready."
