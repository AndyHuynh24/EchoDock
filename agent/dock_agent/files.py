"""Find folders and files anywhere in the user's home folder (including iCloud
Drive and cloud drives like OneDrive), and open them safely.

Searching uses the computer's own index because it is instant: Spotlight
(mdfind) on the Mac, Windows Search on Windows (win/search.py). If it finds
nothing, we fall back to walking the usual folders ourselves. The same code
runs on both; only the index and "open" differ.
"""

import os
import difflib
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home()
WINDOWS = sys.platform == "win32"

KNOWN_FOLDERS = {
    "downloads": HOME / "Downloads",
    "download": HOME / "Downloads",
    "desktop": HOME / "Desktop",
    "documents": HOME / "Documents",
    "docs": HOME / "Documents",
    "pictures": HOME / "Pictures",
    "photos": HOME / "Pictures",
    "music": HOME / "Music",
    "movies": HOME / "Movies",
    "videos": HOME / "Movies",
    "home": HOME,
    "applications": Path("/Applications"),
    "apps": Path("/Applications"),
}
if WINDOWS:
    KNOWN_FOLDERS.update(movies=HOME / "Videos", videos=HOME / "Videos", onedrive=HOME / "OneDrive")
    for name in ("applications", "apps"):
        KNOWN_FOLDERS.pop(name)

# Folders under ~/Library that hold the user's own files.
CLOUD_PREFIXES = (("Library", "CloudStorage"), ("Library", "Mobile Documents"))
SKIP_PARTS = {"Library", "node_modules", "__pycache__", "venv", "cdk.out", "DerivedData", "AppData"}
WALK_ROOTS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads",
              HOME / ("OneDrive" if WINDOWS else "Library/CloudStorage")]
MAX_WALK_DEPTH = 6
MAX_WALK_SECONDS = 3  # walking a big cloud drive can take minutes, so stop early

FILLER_WORDS = {
    "my", "the", "a", "an", "folder", "file", "files", "directory", "please", "for", "in", "on",
    "of", "from", "with", "to", "and", "i", "that", "this", "last", "worked", "called", "named",
}

KINDS = {
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp", ".tiff"},
    "photo": {".png", ".jpg", ".jpeg", ".heic"},
    "video": {".mov", ".mp4", ".m4v", ".avi", ".mkv"},
    "audio": {".mp3", ".m4a", ".wav", ".aac", ".flac"},
    "document": {".doc", ".docx", ".pages", ".txt", ".rtf", ".md", ".odt"},
    "spreadsheet": {".xls", ".xlsx", ".numbers", ".csv"},
    "presentation": {".ppt", ".pptx", ".key"},
    "slide": {".ppt", ".pptx", ".key"},
}

# Opening these could run a program, so Dock never opens them.
BLOCKED_EXTENSIONS = {
    ".app", ".command", ".sh", ".zsh", ".bash", ".tool", ".terminal", ".workflow", ".pkg",
    ".mpkg", ".scpt", ".applescript", ".py", ".rb", ".pl", ".jar", ".dmg", ".exe",
    ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp",
    ".scr", ".lnk", ".reg", ".hta", ".cpl", ".pif", ".appx", ".msix",
}

MAX_RESULTS = 8


class SearchError(Exception):
    """Something to tell the user, e.g. a folder that doesn't exist."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in FILLER_WORDS]


def _user_parts(path: Path) -> tuple[str, ...] | None:
    """The parts of `path` below the home folder (cloud-drive prefix removed),
    or None if it isn't in the home folder."""
    try:
        parts = path.relative_to(HOME).parts
    except ValueError:
        return None
    for prefix in CLOUD_PREFIXES:
        if parts[:2] == prefix:
            return parts[2:]
    return parts


def _visible(path: Path) -> bool:
    """True for the user's own files; False for hidden, system and trash files."""
    parts = _user_parts(path)
    return parts is not None and not any(p.startswith(".") or p in SKIP_PARTS for p in parts)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def where(path: Path) -> str:
    """A short description of the folder that contains `path`, e.g.
    "Documents/school". Empty for the home folder itself and system folders."""
    parts = _user_parts(path.parent)
    return "/".join(parts) if parts else ""


def _when(path: Path) -> str:
    changed = datetime.fromtimestamp(_mtime(path))
    days_ago = (datetime.now().date() - changed.date()).days
    clock = f"{changed.hour % 12 or 12}:{changed:%M %p}"  # (no leading zero, on Mac and Windows)
    if days_ago == 0:
        return f"today at {clock}"
    if days_ago == 1:
        return f"yesterday at {clock}"
    if days_ago < 7:
        return f"{changed.strftime('%A')} at {clock}"
    return f"{changed:%b} {changed.day}, {changed.year}"


def open_in_system(target: Path | str, reveal: bool = False) -> None:
    """Open a file, folder or link the way a double-click would (or show it in
    Finder / File Explorer)."""
    if WINDOWS:
        if reveal:
            subprocess.run(["explorer", f"/select,{target}"])  # (explorer returns 1 even when it worked)
        else:
            os.startfile(str(target))
        return
    subprocess.run(["open", "-R", str(target)] if reveal else ["open", str(target)], check=True)


def _index_names(words: list[str], root: Path, folders: bool | None = None) -> list[Path]:
    """Files (folders=False), folders (True) or both (None) whose name has all
    the words, in that order, from the computer's index."""
    if WINDOWS:
        from dock_agent.win import search
        return search.names(words, root, folders)
    query = _name_query(words)
    if folders:
        query = f'kMDItemContentType == "public.folder" && {query}'
    return _spotlight(query, root)


def _index_text(text: str, root: Path) -> list[Path]:
    """Files with these words in their text (or name), from the computer's index."""
    if WINDOWS:
        from dock_agent.win import search
        return search.text(text, root)
    return _spotlight(text, root)


def _spotlight(query: str, root: Path) -> list[Path]:
    try:
        output = subprocess.run(
            ["mdfind", "-onlyin", str(root), query], capture_output=True, text=True, timeout=8
        ).stdout
    except subprocess.TimeoutExpired:
        return []
    return [Path(line) for line in output.splitlines()[:500] if line]


def _walk(roots: list[Path], folders: bool):
    """Yield folders (or files) under `roots`, skipping hidden and system folders.
    Gives up after MAX_WALK_SECONDS."""
    deadline = time.time() + MAX_WALK_SECONDS
    for root in roots:
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline:
                return
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_PARTS]
            if len(here.parts) - base_depth >= MAX_WALK_DEPTH:
                dirnames.clear()
            for name in dirnames if folders else filenames:
                yield here / name


MAIN_ROOTS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads"]
MAIN_DEPTH = 3          # folders people name out loud are rarely deeper
MAIN_LIMIT = 3000
MAIN_CACHE_SECONDS = 300
_main_cache: tuple[float, list[Path]] = (0.0, [])


def main_folders() -> list[Path]:
    """The folders people name out loud: everything up to MAIN_DEPTH levels
    inside Desktop, Documents and Downloads, shallow ones first (so a big code
    folder can't crowd them out). Cached for a few minutes."""
    global _main_cache
    if time.time() - _main_cache[0] < MAIN_CACHE_SECONDS:
        return _main_cache[1]
    found, level = [], [root for root in MAIN_ROOTS if root.is_dir()]
    for _ in range(MAIN_DEPTH):
        next_level = []
        for folder in level:
            try:
                children = sorted(c for c in folder.iterdir() if c.is_dir())
            except OSError:
                continue
            for child in children:
                if child.name.startswith(".") or child.name in SKIP_PARTS or child.suffix in (".app", ".photoslibrary"):
                    continue
                found.append(child)
                next_level.append(child)
        level = next_level
        if len(found) >= MAIN_LIMIT:
            break
    _main_cache = (time.time(), found[:MAIN_LIMIT])
    return _main_cache[1]


CODE_MARKERS = (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "Makefile")
GENERIC_NAMES = {"src", "lib", "libraries", "tests", "test", "docs", "scripts", "configs", "outputs", "data",
                 "images", "pics", "logs", "models", "assets", "build", "dist", "bin", "desktop", "documents",
                 "pictures", "attachments", "projects"}
MAX_SPOKEN_NAMES = 80


def spoken_folder_names() -> list[str]:
    """Names of the user's own folders that they might say out loud (CS589,
    stat310, PipetteCoach...): the folders in Documents and Desktop and one
    level inside them, but not inside code projects, and not generic names
    like "src". Used so speech mistakes ("Start 310") can be fixed."""
    def is_code(folder: Path) -> bool:
        return any((folder / marker).exists() for marker in CODE_MARKERS)

    top, inside = [], []
    for root in (HOME / "Documents", HOME / "Desktop"):
        if not root.is_dir():
            continue
        for first in sorted(root.iterdir()):
            if not first.is_dir() or first.name.startswith("."):
                continue
            top.append(first.name)
            if not is_code(first):
                inside += [c.name for c in sorted(first.iterdir()) if c.is_dir() and not c.name.startswith(".")]
    names = [n for n in dict.fromkeys(top + inside)
             if n.lower() not in GENERIC_NAMES and len(n) <= 24 and " copy" not in n and not re.match(r"\d{4}-\d\d", n)]
    # Class codes first (CS589, stat 310): they're the ones speech gets wrong most.
    codes = [n for n in names if re.fullmatch(r"[A-Za-z]{2,5}[ _-]?\d{3}[A-Za-z]?", n)]
    return (codes + [n for n in names if n not in codes])[:MAX_SPOKEN_NAMES]


def _name_query(words: list[str]) -> str:
    # Words only contain a-z and 0-9, so they are safe inside the query.
    # "stat 310" becomes *stat*310*, which also matches "STAT310" and "Stat-310".
    return f'kMDItemFSName == "*{"*".join(words)}*"cd'


def find_folders(name: str, walk: bool = True, close: bool = True) -> list[Path]:
    """Folders whose name matches `name`, best match first. close=False: no
    near spellings ("start 310" for stat310), only names with all the words."""
    words = _words(name)
    if not words:
        return []
    found = [p for p in _index_names(words, HOME, folders=True) if p.is_dir() and _visible(p)]
    if not found:
        # Spotlight missed it (or isn't indexing). Quick checks first, among the
        # user's main folders: all the words, then a very close name for misheard
        # ones ("start 310" for stat310). The slow deep scan is the last resort.
        found = [p for p in main_folders() if all(w in _norm(p.name) for w in words)]
    if not found and close:
        folders = {}
        for folder in main_folders():
            folders.setdefault(_norm(folder.name), folder)  # (the shallowest one wins)
        close = difflib.get_close_matches("".join(words), list(folders), n=1, cutoff=0.8)
        found = [folders[close[0]]] if close else []
    if not found and walk:
        found = [p for p in _walk(WALK_ROOTS, folders=True) if all(w in _norm(p.name) for w in words)]

    target = "".join(words)

    def rank(path: Path):
        name = _norm(path.name)
        closeness = 0 if name == target else 1 if name.startswith(target) else 2
        return (closeness, len(path.parts), -_mtime(path))

    return sorted(found, key=rank)


def resolve_folder(name: str) -> Path | None:
    known = KNOWN_FOLDERS.get(" ".join(_words(name)))
    if known:
        return known
    matches = find_folders(name)
    return matches[0] if matches else None


def open_folder(name: str, close: bool = True) -> dict:
    known = KNOWN_FOLDERS.get(" ".join(_words(name)))
    matches = [known] if known else find_folders(name, close=close)
    if not matches:
        raise SearchError(f"I couldn't find a folder called {name} anywhere in your files.")
    folder = matches[0]
    open_in_system(folder)
    return {"folder": folder.name or str(folder), "where": where(folder), "other_matches": len(matches) - 1}


def _folder_in_words(words: list[str]) -> tuple[Path | None, list[str]]:
    """People often name a folder inside a file request ("my stat310 homework").
    If one of the words is exactly the name of a folder, return that folder and
    the other words. When several words name folders, the most specific one
    (the name with the fewest folders) wins."""
    best = None
    for word in words:
        if len(word) < 3:
            continue
        folders = [p for p in find_folders(word, walk=False) if _norm(p.name) == word]
        if folders and (best is None or len(folders) < best[0]):
            best = (len(folders), folders[0], word)
    if best is None:
        return None, words
    return best[1], [w for w in words if w != best[2]]


def _path_has_words(path: Path, words: list[str]) -> bool:
    """True if every word appears in the file's name or in one of its folder names."""
    full = _norm("/".join(_user_parts(path) or path.parts))
    return all(word in full for word in words)


def _with_words_inside(files: list[Path], words: list[str], root: Path) -> list[Path]:
    """Files where every word is in the name, a folder name, or the text inside
    the file (Spotlight indexes the text of PDFs, documents and code). So "stat525
    hw4" finds Downloads/hw4.Rmd, whose first line says "STAT 525 Homework 4"."""
    inside = {}
    for word in words:
        # "stat525" also matches "STAT 525" in the text.
        inside[word] = set(_index_text(" ".join(re.findall(r"[a-z]+|[0-9]+", word)), root))
    if not files:  # (no folder given: only files Spotlight found can match)
        files = list(set().union(*inside.values()))
    return [p for p in files if all(word in _norm(str(p)) or p in inside[word] for word in words)]


def find_files(name: str = "", kind: str = "", folder: str = "", days: int = 0) -> dict:
    words = _words(name)
    if folder:
        root = resolve_folder(folder)
        if root is None:
            raise SearchError(f"I couldn't find a folder called {folder}.")
    else:
        root, words = _folder_in_words(words)

    if root is not None:
        # Inside one folder: match the words against folder names too, so
        # "homework" finds stat310/homework/Andy_hw3.pdf.
        everything = list(_walk([root], folders=False))
        candidates = [p for p in everything if _path_has_words(p, words)]
    elif words:
        candidates = _index_names(words, HOME) or [
            p for p in _walk(WALK_ROOTS, folders=False) if all(w in _norm(p.name) for w in words)
        ]
    else:
        candidates = list(_walk(WALK_ROOTS, folders=False))
    found_inside = False
    if words and not candidates:
        candidates = _with_words_inside(everything if root is not None else [], words, root or HOME)
        found_inside = bool(candidates)

    kind_key = _norm(kind).removesuffix("s")
    extensions = KINDS.get(kind_key) or ({"." + kind_key} if kind_key else set())
    matching = [
        p for p in candidates
        if p.is_file() and _visible(p) and (not extensions or p.suffix.lower() in extensions)
    ]
    matching.sort(key=_mtime, reverse=True)

    results, note = matching, ("No file has all those words in its name, so these have them inside." if found_inside else "")
    if days:
        # Calendar days: 1 = today, 2 = since the start of yesterday.
        start = (datetime.now() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        results = [p for p in matching if _mtime(p) >= start.timestamp()]
        if not results and matching:
            # People are loose about "yesterday", so show the newest matches instead of nothing.
            results = matching
            note = "None of the matches were changed in that time, so these are the newest ones."

    return {
        "total": len(results),
        "note": note,
        "files": [
            {"name": p.name, "where": where(p), "changed": _when(p), "path": str(p)}
            for p in results[:MAX_RESULTS]
        ],
    }


def open_path(path: str, show_in_finder: bool = False) -> dict:
    target = Path(path).expanduser()
    if not target.exists():
        raise SearchError("That file isn't there anymore.")
    if not _visible(target):
        raise SearchError("I can only open things in your own folders.")
    runs_code = target.suffix.lower() in BLOCKED_EXTENSIONS or (
        not WINDOWS and target.is_file() and not target.suffix and os.access(target, os.X_OK)
    )
    if runs_code and not show_in_finder:
        raise SearchError(f"To be safe, I won't open {target.name} because it could run a program. "
                          f"I can show it in {'File Explorer' if WINDOWS else 'Finder'} instead.")
    open_in_system(target, reveal=show_in_finder)
    return {"name": target.name, "where": where(target)}
