"""Lists and reads documents for search_my_stuff (Mac and Windows). The index lives on the server."""

import os
import time
from pathlib import Path

from dock_agent.files import SKIP_PARTS, WALK_ROOTS, WINDOWS, _visible

DOC_TYPES = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".pptx", ".txt", ".md", ".rmd", ".qmd", ".tex"}
MAX_DOCUMENTS = 2000
MAX_BYTES = 30_000_000  # larger files are usually scans or books
MAX_CHARS = 40_000
WALK_SECONDS = 20
DATA_FOLDERS = {"data", "dataset", "datasets", "logs", "log", "output", "outputs", "results", "raw", "build", "dist"}
MANY_PLAIN = 30  # folders with more text files than this are data
PLAIN = {".txt", ".md", ".tex"}


def list_documents() -> dict:
    """Documents in the user's folders, newest first."""
    found = []
    deadline = time.time() + WALK_SECONDS
    for root in WALK_ROOTS:
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline:
                break
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_PARTS
                           and d.lower() not in DATA_FOLDERS and not d.endswith("_files")
                           and not (Path(dirpath) / d / ".git").exists()]
            plain_here = sum(1 for n in filenames if Path(n).suffix.lower() in PLAIN)
            for name in filenames:
                path = Path(dirpath) / name
                suffix = path.suffix.lower()
                if suffix not in DOC_TYPES or name.startswith(("~$", ".")) or (suffix in PLAIN and plain_here > MANY_PLAIN):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if 0 < stat.st_size <= MAX_BYTES and _visible(path):
                    found.append({"path": str(path), "name": name, "folder": path.parent.name,
                                  "modified": stat.st_mtime})
    found.sort(key=lambda d: -d["modified"])
    return {"documents": found[:MAX_DOCUMENTS], "total": len(found)}


def document_texts(paths: list[str]) -> dict:
    """Text of each document (up to MAX_CHARS), or ""."""
    if WINDOWS:
        from dock_agent.win import reading
    else:
        from dock_agent import reading
    texts = {}
    for path in paths[:20]:
        try:
            texts[path] = reading.file_text(path)[:MAX_CHARS]
        except Exception:
            texts[path] = ""
    return {"texts": texts}
