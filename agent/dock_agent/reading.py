"""Get the text the user means by "read this" or "summarize this":

1. Text selected in the app in front (asked through Accessibility).
2. If the app doesn't share that, copy the selection with Command-C and read
   the clipboard. The clipboard is put back exactly as it was afterwards.
3. Otherwise, the document open in the front window (PDF, Word, text...).

Or a specific file, e.g. one found with find_files.
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
KEY_C = 8  # the "c" key
KEY_V = 9  # the "v" key
KEY_RIGHT = 124  # the right arrow
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
    """Press Command-C, read the copied text, then put the clipboard back."""
    board = NSPasteboard.generalPasteboard()
    saved = _clipboard()
    before = board.changeCount()
    _command(KEY_C)
    for _ in range(10):
        time.sleep(0.05)
        if board.changeCount() != before:
            break
    if board.changeCount() == before:
        return ""  # nothing was selected
    text = str(board.stringForType_(NSPasteboardTypeString) or "")
    _restore(saved)
    return text


def _focused(pid: int):
    """The part of the app that has the keyboard. VS Code, Chrome and other
    web-based apps only share it (and its selected text) once asked to."""
    app = AXUIElementCreateApplication(pid)
    AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)
    return _get(app, "AXFocusedUIElement")


def selection() -> dict:
    """Only the text selected in the app in front (for "fix the grammar in this")."""
    app_name, pid = front_app()
    focused = _focused(pid)
    text = str(_get(focused, "AXSelectedText") or "") if focused is not None else ""
    if not text.strip():
        text = _copy_selection()
    if not text.strip():
        raise ReadError(f"Select the text in {app_name} that you want me to work on, then ask again.")
    return {"app": app_name, "pid": pid, "text": text}


def replace_selection(pid: int, text: str) -> str:
    """Put `text` in place of the selection, in the app's own text: through
    Accessibility if the app allows it, else by pasting it (and putting the
    clipboard back). Either way the app's own Undo undoes it."""
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
    time.sleep(0.6)  # (let the app take the paste before the clipboard goes back)
    _restore(saved)
    return "paste"


def insert_after_selection(pid: int, text: str) -> str:
    """Put `text` on its own lines under the selection, leaving the selected
    text as it is. (The right arrow moves the cursor to the end of a selection
    in any Mac or web text box.)"""
    _command(KEY_RIGHT, 0)
    time.sleep(0.1)
    return replace_selection(pid, text)


TEXT_ROLES = {"AXTextArea", "AXTextField"}
WINDOW_TEXT_CHARS = 1500


def window_text(pid: int) -> str:
    """The start of the document in the app's main window, e.g. behind its Save
    window, so Dock can suggest a folder from what it's about. The saved file
    if it has one, else the window's biggest text area (TextEdit, Mail, Notes...)."""
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
