"""Find and open folders and files in the user's home folder, including cloud drives.

Uses Spotlight on macOS and Windows Search on Windows, with a folder walk as fallback.
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

# Folders under ~/Library with user files.
CLOUD_PREFIXES = (("Library", "CloudStorage"), ("Library", "Mobile Documents"))
SKIP_PARTS = {"Library", "node_modules", "__pycache__", "venv", "cdk.out", "DerivedData", "AppData"}
WALK_ROOTS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads",
              HOME / ("OneDrive" if WINDOWS else "Library/CloudStorage")]
MAX_WALK_DEPTH = 6
MAX_WALK_SECONDS = 3

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

# Executable types Dock never opens.
BLOCKED_EXTENSIONS = {
    ".app", ".command", ".sh", ".zsh", ".bash", ".tool", ".terminal", ".workflow", ".pkg",
    ".mpkg", ".scpt", ".applescript", ".py", ".rb", ".pl", ".jar", ".dmg", ".exe",
    ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp",
    ".scr", ".lnk", ".reg", ".hta", ".cpl", ".pif", ".appx", ".msix",
}

MAX_RESULTS = 8


class SearchError(Exception):
    """An error message meant for the user."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in FILLER_WORDS]


def _user_parts(path: Path) -> tuple[str, ...] | None:
    """Parts of `path` below the home folder, or None."""
    try:
        parts = path.relative_to(HOME).parts
    except ValueError:
        return None
    for prefix in CLOUD_PREFIXES:
        if parts[:2] == prefix:
            return parts[2:]
    return parts


def _visible(path: Path) -> bool:
    """True for the user's own files (not hidden, system or trash)."""
    parts = _user_parts(path)
    return parts is not None and not any(p.startswith(".") or p in SKIP_PARTS for p in parts)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def where(path: Path) -> str:
    """Short label for the containing folder, e.g. "Documents/school"."""
    parts = _user_parts(path.parent)
    return "/".join(parts) if parts else ""


def _when(path: Path) -> str:
    changed = datetime.fromtimestamp(_mtime(path))
    days_ago = (datetime.now().date() - changed.date()).days
    clock = f"{changed.hour % 12 or 12}:{changed:%M %p}"
    if days_ago == 0:
        return f"today at {clock}"
    if days_ago == 1:
        return f"yesterday at {clock}"
    if days_ago < 7:
        return f"{changed.strftime('%A')} at {clock}"
    return f"{changed:%b} {changed.day}, {changed.year}"


def open_in_system(target: Path | str, reveal: bool = False) -> None:
    """Open a file, folder or link, or reveal it in Finder / File Explorer."""
    if WINDOWS:
        if reveal:
            subprocess.run(["explorer", f"/select,{target}"])  # explorer returns 1 even on success
        else:
            os.startfile(str(target))
        return
    subprocess.run(["open", "-R", str(target)] if reveal else ["open", str(target)], check=True)


def _index_names(words: list[str], root: Path, folders: bool | None = None) -> list[Path]:
    """Index search by name. folders: False files, True folders, None both."""
    if WINDOWS:
        from dock_agent.win import search
        return search.names(words, root, folders)
    query = _name_query(words)
    if folders:
        query = f'kMDItemContentType == "public.folder" && {query}'
    return _spotlight(query, root)


def _index_text(text: str, root: Path) -> list[Path]:
    """Index search by content or name."""
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
    """Walk `roots`, skipping hidden and system folders, up to MAX_WALK_SECONDS."""
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
MAIN_DEPTH = 3
MAIN_LIMIT = 3000
MAIN_CACHE_SECONDS = 300
_main_cache: tuple[float, list[Path]] = (0.0, [])


def main_folders() -> list[Path]:
    """Folders up to MAIN_DEPTH deep in Desktop, Documents and Downloads (cached)."""
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
    """Folder names the user might say, for correcting speech (skips code projects and generic names)."""
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
    # Class codes first; speech gets them wrong most.
    codes = [n for n in names if re.fullmatch(r"[A-Za-z]{2,5}[ _-]?\d{3}[A-Za-z]?", n)]
    return (codes + [n for n in names if n not in codes])[:MAX_SPOKEN_NAMES]


def _name_query(words: list[str]) -> str:
    # Words are [a-z0-9] only, so they're safe in the query.
    return f'kMDItemFSName == "*{"*".join(words)}*"cd'


def find_folders(name: str, walk: bool = True, close: bool = True) -> list[Path]:
    """Folders matching `name`, best first. close=False disables fuzzy matches."""
    words = _words(name)
    if not words:
        return []
    found = [p for p in _index_names(words, HOME, folders=True) if p.is_dir() and _visible(p)]
    if not found:
        # Spotlight missed it: try the main folders, then fuzzy names, then a deep scan.
        found = [p for p in main_folders() if all(w in _norm(p.name) for w in words)]
    if not found and close:
        folders = {}
        for folder in main_folders():
            folders.setdefault(_norm(folder.name), folder)
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
    """If a word names a folder ("my stat310 homework"), return that folder and the other words."""
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
    """True if every word is in the file or folder names."""
    full = _norm("/".join(_user_parts(path) or path.parts))
    return all(word in full for word in words)


def _with_words_inside(files: list[Path], words: list[str], root: Path) -> list[Path]:
    """Files where every word is in the name, a folder name or the file's text."""
    inside = {}
    for word in words:
        inside[word] = set(_index_text(" ".join(re.findall(r"[a-z]+|[0-9]+", word)), root))
    if not files:
        files = list(set().union(*inside.values()))
    return [p for p in files if all(word in _norm(str(p)) or p in inside[word] for word in words)]


JUST_ADDED_SECONDS = 3600


def _added_recently() -> list[Path]:
    """Files added to the user's folders in the last hour."""
    if WINDOWS:
        return []
    found = []
    for root in WALK_ROOTS[:2]:
        try:
            out = subprocess.run(["mdfind", "-onlyin", str(root), f"kMDItemDateAdded >= $time.now(-{JUST_ADDED_SECONDS})"],
                                 capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        found += [Path(line) for line in out.splitlines()
                  if line and not SKIP_PARTS & set(Path(line).parts) and Path(line).is_file()]
    return found


def find_files(name: str = "", kind: str = "", folder: str = "", days: int = 0) -> dict:
    words = _words(name)
    if folder:
        root = resolve_folder(folder)
        if root is None:
            raise SearchError(f"I couldn't find a folder called {folder}.")
    else:
        root, words = _folder_in_words(words)

    if root is not None:
        # Match words against folder names too.
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
    if root == resolve_folder("downloads") and not words:
        # New files can be saved outside Downloads too.
        matching += [p for p in _added_recently() if p not in matching and _visible(p)
                     and (not extensions or p.suffix.lower() in extensions)]
    matching.sort(key=_mtime, reverse=True)

    results, note = matching, ("No file has all those words in its name, so these have them inside." if found_inside else "")
    if days:
        # Calendar days: 1 = today, 2 = since yesterday.
        start = (datetime.now() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        results = [p for p in matching if _mtime(p) >= start.timestamp()]
        if not results and matching:
            # Loose "yesterday": fall back to the newest matches.
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
