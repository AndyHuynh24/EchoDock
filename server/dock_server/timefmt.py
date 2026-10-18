"""Dates and times written the same way on Mac and Windows. Python's "%-I"
(an hour without a leading zero: "9:05 AM") only works on Mac and Linux;
Windows spells it "%#I"."""

import sys
from datetime import date, datetime


def strftime(moment: date | datetime, pattern: str) -> str:
    return moment.strftime(pattern.replace("%-", "%#") if sys.platform == "win32" else pattern)
