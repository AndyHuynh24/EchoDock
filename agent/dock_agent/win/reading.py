"""Selected or document text on Windows, and writing improved text back.

Reads via UI Automation, falling back to a Ctrl+C copy. Writes by pasting, since UI
Automation can't replace just the selection. The clipboard is always restored.
"""

import html
import re
import time
import zipfile
from pathlib import Path

import uiautomation as auto
import win32con

from dock_agent.files import _visible
from dock_agent.win import menus, uia, winapi

MAX_CHARS = 40_000
WINDOW_TEXT_CHARS = 1500
PLAIN_TYPES = {".txt", ".md", ".rmd", ".qmd", ".csv", ".py", ".r", ".js", ".ts", ".json", ".tex", ".log"}
ZIPPED_TEXT = {".docx": "word/document.xml", ".pptx": None, ".odt": "content.xml", ".odp": "content.xml"}
TEXT_TYPES = {auto.ControlType.DocumentControl, auto.ControlType.EditControl}


class ReadError(Exception):
    pass


# ---- files ----

def _xml_text(xml: str) -> str:
    xml = re.sub(r"</(w:p|text:p|text:h|a:p)>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _rtf_text(rtf: str) -> str:
    rtf = re.sub(r"\{\\\*[^{}]*\}", "", rtf)
    rtf = re.sub(r"\\par[d]?\b ?", "\n", rtf)
    rtf = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252"), rtf)
    rtf = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", rtf)
    return rtf


def file_text(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file() or not _visible(file):
        raise ReadError("I can't find that file.")
    suffix = file.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(file)).pages[:60])
        elif suffix in ZIPPED_TEXT:
            with zipfile.ZipFile(file) as archive:
                names = [ZIPPED_TEXT[suffix]] if ZIPPED_TEXT[suffix] else sorted(
                    n for n in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
                text = "\n".join(_xml_text(archive.read(n).decode("utf-8", "ignore")) for n in names)
        elif suffix == ".rtf":
            text = _rtf_text(file.read_text(errors="ignore"))
        elif suffix in (".html", ".htm"):
            text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", "", file.read_text(errors="ignore"))))
        elif suffix in PLAIN_TYPES:
            text = file.read_text(errors="ignore")
        else:
            raise ReadError(f"I can't read {file.suffix} files yet.")
    except ReadError:
        raise
    except Exception as e:
        print(f"Couldn't read {file}: {e!r}")
        raise ReadError(f"I couldn't read {file.name}.")
    if not text.strip():
        raise ReadError(f"I couldn't find any text in {file.name}.")
    return text


# ---- selection ----

def _text_pattern(control):
    """Text pattern of the control or its parent."""
    for _ in range(4):
        if control is None:
            return None
        found = uia.pattern(control, "TextPattern")
        if found is not None:
            return found
        try:
            control = control.GetParentControl()
        except Exception:
            return None
    return None


def selected_by_uia() -> str:
    """Selected text via UI Automation (nothing copied)."""
    try:
        found = _text_pattern(uia.focused())
        ranges = found.GetSelection() if found is not None else []
        return "".join(r.GetText(-1) for r in ranges) if ranges else ""
    except Exception:
        return ""


def _copy_selection() -> str:
    """Copy with Ctrl+C, read the clipboard, then restore it."""
    saved = winapi.save_clipboard()
    before = winapi.clipboard_number()
    winapi.keys(win32con.VK_CONTROL, ord("C"))
    for _ in range(10):
        time.sleep(0.05)
        if winapi.clipboard_number() != before:
            break
    if winapi.clipboard_number() == before:
        return ""
    text = winapi.clipboard_text()
    winapi.restore_clipboard(saved)
    return text


def selection() -> dict:
    app_name, pid = menus.front_app()
    text = selected_by_uia()
    if not text.strip():
        text = _copy_selection()
    if not text.strip():
        raise ReadError(f"Select the text in {app_name} that you want me to work on, then ask again.")
    return {"app": app_name, "pid": pid, "text": text}


def replace_selection(pid: int, text: str) -> str:
    """Paste `text` over the selection, then restore the clipboard."""
    saved = winapi.save_clipboard()
    winapi.set_clipboard_text(text)
    winapi.keys(win32con.VK_CONTROL, ord("V"))
    time.sleep(0.6)
    winapi.restore_clipboard(saved)
    return "paste"


def insert_after_selection(pid: int, text: str) -> str:
    """Insert `text` below the selection, leaving it unchanged."""
    winapi.keys(win32con.VK_RIGHT)
    time.sleep(0.1)
    return replace_selection(pid, text)


# ---- window text ----

def _text_of(control, limit: int) -> str:
    found = uia.pattern(control, "TextPattern")
    if found is not None:
        try:
            return found.DocumentRange.GetText(limit)
        except Exception:
            pass
    found = uia.pattern(control, "ValuePattern")
    if found is not None:
        try:
            return str(found.Value or "")[:limit]
        except Exception:
            pass
    return ""


def window_text(pid: int, limit: int = WINDOW_TEXT_CHARS) -> str:
    """Text of the window's largest document or text box."""
    window = uia.window(winapi.window_of(pid))
    if window is None:
        return ""
    boxes = [f for f in uia.find_all(window, max_seconds=1.5)
             if f.type in TEXT_TYPES and f.rect and not f.password and not f.offscreen]
    boxes.sort(key=lambda f: f.rect[2] * f.rect[3], reverse=True)
    best = ""
    for box in boxes[:5]:
        control = box.control()
        text = _text_of(control, limit) if control is not None else ""
        if len(text.strip()) > len(best.strip()):
            best = text
    return best[:limit]


def read_text(path: str = "") -> dict:
    if path:
        return {"source": "file", "title": Path(path).name, "text": file_text(path)[:MAX_CHARS]}
    app_name, pid = menus.front_app()
    selected = selected_by_uia() or _copy_selection()
    if selected.strip():
        return {"source": "selection", "title": f"your selection in {app_name}", "text": selected[:MAX_CHARS]}
    window_title, document = menus.front_window(pid)
    if document:
        try:
            return {"source": "document", "title": Path(document).name, "text": file_text(document)[:MAX_CHARS]}
        except ReadError:
            pass
    text = window_text(pid, MAX_CHARS)
    if text.strip():
        return {"source": "document", "title": window_title or app_name, "text": text}
    raise ReadError(f"Select some text in {app_name} first, or open a document. In a browser, Ctrl+A selects the whole page.")
