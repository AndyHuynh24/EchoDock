"""Shared workspace storage and name matching (Mac and Windows)."""

import difflib
import json
import re
from pathlib import Path

WORKSPACE_DIR = Path.home() / ".dock" / "workspaces"


class WorkspaceError(Exception):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def bare(name: str) -> str:
    """Drop a trailing "workspace"."""
    return re.sub(r"(\s*workspace)+$", "", name.strip(), flags=re.IGNORECASE).strip() or name.strip()


def list_all() -> list[str]:
    if not WORKSPACE_DIR.is_dir():
        return []
    return [bare(json.loads(p.read_text())["name"]) for p in sorted(WORKSPACE_DIR.glob("*.json"))]


def _load(name: str) -> dict:
    # Normalized keys; fall back to the closest name for speech errors ("stat 3:10").
    files = {_norm(bare(json.loads(p.read_text())["name"])): p for p in WORKSPACE_DIR.glob("*.json")} if WORKSPACE_DIR.is_dir() else {}
    key = _norm(bare(name))
    match = files.get(key) or next((p for stem, p in files.items() if key and (stem.startswith(key) or key in stem)), None)
    if match is None:
        close = difflib.get_close_matches(key, list(files), n=1, cutoff=0.75)
        match = files[close[0]] if close else None
    if match is None:
        saved = ", ".join(list_all()) or "none yet"
        raise WorkspaceError(f"I don't have a workspace called {name}. Saved workspaces: {saved}.")
    return json.loads(match.read_text())
