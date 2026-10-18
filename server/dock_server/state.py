"""What Dock remembers while the server runs. Dock is single-user for now, so
one shared State object is enough."""

from dataclasses import dataclass, field
from pathlib import Path

# Small files the server keeps between runs (e.g. which shortcut-pad buttons to show per app).
DATA_DIR = Path(__file__).resolve().parent.parent / ".data"


@dataclass
class State:
    # The menu item app_help last pointed to, for "do it": {"app", "pid", "path"}.
    last_suggestion: dict = field(default_factory=dict)
    # How often each menu item was asked about: (app, path tuple) -> count.
    times_asked: dict = field(default_factory=dict)
    # Questions asked today, for the end-of-day recap: (date, app, item name).
    questions: list = field(default_factory=list)
    # The shortcut pad currently shown on phones.
    pad: dict = field(default_factory=dict)
    # The latest Downloads tidy-up suggestions: [{"file", "to", "new_folder", "why"}].
    tidy_plan: list = field(default_factory=list)
    # New downloads Dock suggested a folder for, not moved yet: file -> {"file", "to", "new_folder", "why"}.
    new_downloads: dict = field(default_factory=dict)
    # The folder Dock suggested for the Save window open on the Mac: {"file", "to", "new_folder", "why", "app"}.
    save_suggestion: dict = field(default_factory=dict)
    # When Dock last moved files (so "undo" right after means put them back).
    last_move_at: float = 0.0
    # Shortcuts the user asked about, for break flashcards: (app, path tuple) -> card.
    shortcuts_seen: dict = field(default_factory=dict)
