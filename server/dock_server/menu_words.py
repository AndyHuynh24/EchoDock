"""Small helpers for menu item names, shared by app help and the shortcut pad."""

# Menu items Dock will not click for the user, to be safe.
RISKY_WORDS = ("delete", "erase", "remove", "trash", "quit", "close", "discard", "revert", "log out", "shut down", "restart")


def display_name(title: str) -> str:
    """Menu titles like "Export…" read better without the dots."""
    return title.rstrip("…. ")


# Safe to do when the user's own words ask for it: closing a window or tab never
# loses work silently (Mac apps ask about unsaved changes first).
OK_WHEN_ASKED = ("close",)


def is_risky(title: str, asked: str = "") -> bool:
    """True for items Dock won't click by itself. `asked` is what the user said:
    "close this window" may close a window, but "do it" never closes anything."""
    title = title.lower()
    return any(word in title and not (word in OK_WHEN_ASKED and word in asked.lower()) for word in RISKY_WORDS)
