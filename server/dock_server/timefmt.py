"""Cross-platform time formatting ("%-I" doesn't work on Windows)."""

import sys
from datetime import date, datetime


def strftime(moment: date | datetime, pattern: str) -> str:
    return moment.strftime(pattern.replace("%-", "%#") if sys.platform == "win32" else pattern)
