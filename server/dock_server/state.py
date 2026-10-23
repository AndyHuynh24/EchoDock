"""In-memory state for the running server (single user)."""

from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / ".data"


@dataclass
class State:
    # Last menu item app_help pointed to, for "do it".
    last_suggestion: dict = field(default_factory=dict)
    # (app, path) -> times asked
    times_asked: dict = field(default_factory=dict)
    # (date, app, item) asked today, for the recap
    questions: list = field(default_factory=list)
    pad: dict = field(default_factory=dict)
    # Latest Downloads tidy-up suggestions
    tidy_plan: list = field(default_factory=list)
    tidy_plan_at: float = 0.0
    # New downloads with a suggested folder, not moved yet
    new_downloads: dict = field(default_factory=dict)
    # Suggested folder for the open Save dialog
    save_suggestion: dict = field(default_factory=dict)
    # For undoing the last move
    last_move_at: float = 0.0
    # Shortcuts asked about, for break flashcards
    shortcuts_seen: dict = field(default_factory=dict)
