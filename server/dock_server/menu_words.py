"""Helpers for menu item names."""

# Menu items Dock never clicks.
RISKY_WORDS = ("delete", "erase", "remove", "trash", "quit", "close", "discard", "revert", "log out", "shut down", "restart")


def display_name(title: str) -> str:
    return title.rstrip("…. ")


# Allowed only when the user asks for them directly.
OK_WHEN_ASKED = ("close",)


def is_risky(title: str, asked: str = "") -> bool:
    """True for items Dock won't click on "do it"."""
    title = title.lower()
    return any(word in title and not (word in OK_WHEN_ASKED and word in asked.lower()) for word in RISKY_WORDS)
