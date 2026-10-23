"""Text for "read this" / "summarize this": the selection (via Accessibility, or a
clipboard copy that is restored afterwards), else the front document, or a given file.
"""

import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from ApplicationServices import AXUIElementCreateApplication, AXUIElementSetAttributeValue
from Foundation import NSURL
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    PDFDocument,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

from dock_agent.files import _visible
from dock_agent.menus import _get, front_app

MAX_CHARS = 40_000
KEY_C = 8
KEY_V = 9
KEY_RIGHT = 124
TEXTUTIL_TYPES = {".doc", ".docx", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive"}
PLAIN_TYPES = {".txt", ".md", ".rmd", ".qmd", ".csv", ".py", ".r", ".js", ".ts", ".json", ".tex", ".log"}


class ReadError(Exception):
    pass


def file_text(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file() or not _visible(file):
        raise ReadError("I can't find that file.")
    suffix = file.suffix.lower()
    if suffix == ".pdf":
        document = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(file)))
        text = str(document.string() or "") if document else ""
    elif suffix in TEXTUTIL_TYPES:
        text = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(file)],
                              capture_output=True, text=True, timeout=15).stdout
    elif suffix in PLAIN_TYPES:
        text = file.read_text(errors="ignore")
    else:
        raise ReadError(f"I can't read {file.suffix} files yet.")
    if not text.strip():
        raise ReadError(f"I couldn't find any text in {file.name}.")
    return text


def _clipboard() -> list[dict]:
    return [{t: item.dataForType_(t) for t in item.types()} for item in (NSPasteboard.generalPasteboard().pasteboardItems() or [])]


def _restore(saved: list[dict]) -> None:
    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    items = []
    for types in saved:
        item = NSPasteboardItem.alloc().init()
        for kind, data in types.items():
            if data is not None:
                item.setData_forType_(data, kind)
        items.append(item)
    if items:
        board.writeObjects_(items)


def _command(key: int, flags: int = kCGEventFlagMaskCommand) -> None:
    for key_down in (True, False):
        event = CGEventCreateKeyboardEvent(None, key, key_down)
        CGEventSetFlags(event, flags)
        CGEventPost(kCGHIDEventTap, event)


def _copy_selection() -> str:
    """Copy with Command-C, read the clipboard, then restore it."""
    board = NSPasteboard.generalPasteboard()
    saved = _clipboard()
    before = board.changeCount()
    _command(KEY_C)
    for _ in range(10):
        time.sleep(0.05)
        if board.changeCount() != before:
            break
    if board.changeCount() == before:
        return ""
    text = str(board.stringForType_(NSPasteboardTypeString) or "")
    _restore(saved)
    return text


def _focused(pid: int):
    """The focused element (Chromium apps expose it only on request)."""
    app = AXUIElementCreateApplication(pid)
    AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    return _get(app, "AXFocusedUIElement")


def selection() -> dict:
    """Only the selected text in the front app."""
    app_name, pid = front_app()
    focused = _focused(pid)
    text = str(_get(focused, "AXSelectedText") or "") if focused is not None else ""
    if not text.strip():
        text = _copy_selection()
    if not text.strip():
        raise ReadError(f"Select the text in {app_name} that you want me to work on, then ask again.")
    return {"app": app_name, "pid": pid, "text": text}


def replace_selection(pid: int, text: str) -> str:
    """Replace the selection via Accessibility, or by pasting. The app's Undo reverts it."""
    focused = _get(AXUIElementCreateApplication(pid), "AXFocusedUIElement")
    before = str(_get(focused, "AXValue") or "") if focused is not None else ""
    if focused is not None and before and AXUIElementSetAttributeValue(focused, "AXSelectedText", text) == 0:
        after = str(_get(focused, "AXValue") or "")
        if after != before and text[:40] in after:
            return "accessibility"
    saved = _clipboard()
    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setString_forType_(text, NSPasteboardTypeString)
    _command(KEY_V)
    time.sleep(0.6)
    _restore(saved)
    return "paste"


def insert_after_selection(pid: int, text: str) -> str:
    """Insert `text` below the selection, leaving it unchanged."""
    _command(KEY_RIGHT, 0)
    time.sleep(0.1)
    return replace_selection(pid, text)


TEXT_ROLES = {"AXTextArea", "AXTextField"}
WINDOW_TEXT_CHARS = 1500


def window_text(pid: int) -> str:
    """Start of the document behind a Save dialog (the saved file, else the largest text area)."""
    app = AXUIElementCreateApplication(pid)
    window = _get(app, "AXMainWindow") or _get(app, "AXFocusedWindow")
    if window is None:
        return ""
    document = _get(window, "AXDocument")
    if document:
        try:
            return file_text(unquote(urlparse(str(document)).path))[:WINDOW_TEXT_CHARS]
        except ReadError:
            pass
    best, stack, seen = "", [window], 0
    while stack and seen < 1500:
        element = stack.pop()
        seen += 1
        if str(_get(element, "AXRole") or "") in TEXT_ROLES and str(_get(element, "AXSubrole") or "") != "AXSecureTextField":
            value = str(_get(element, "AXValue") or "")
            if len(value) > len(best):
                best = value
        stack.extend(_get(element, "AXChildren") or [])
    return best[:WINDOW_TEXT_CHARS]


def read_text(path: str = "") -> dict:
    if path:
        return {"source": "file", "title": Path(path).name, "text": file_text(path)[:MAX_CHARS]}

    app_name, pid = front_app()
    app = AXUIElementCreateApplication(pid)

    focused = _focused(pid)
    selected = str(_get(focused, "AXSelectedText") or "") if focused is not None else ""
    if not selected.strip():
        selected = _copy_selection()
    if selected.strip():
        return {"source": "selection", "title": f"your selection in {app_name}", "text": selected[:MAX_CHARS]}

    window = _get(app, "AXFocusedWindow") or _get(app, "AXMainWindow")
    document = _get(window, "AXDocument") if window is not None else None
    if document:
        file = unquote(urlparse(str(document)).path)
        return {"source": "document", "title": Path(file).name, "text": file_text(file)[:MAX_CHARS]}

    raise ReadError(f"Select some text in {app_name} first, or open a document. In a browser, Command A selects the whole page.")
