"""Downloads tidy-up on the agent side: overview, safe moves with undo, and new-download detection."""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from dock_agent import link
from dock_agent.files import HOME, SKIP_PARTS, WINDOWS, _visible, _when

DOWNLOADS = HOME / "Downloads"
UNDO_FILE = HOME / ".dock" / "last_moves.json"
DESTINATION_ROOTS = [HOME / "Documents", HOME / "Desktop", HOME / "Library" / "CloudStorage",
                     HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs", HOME / "OneDrive"]
MAX_FILES = 40
MAX_FOLDERS = 600
FOLDER_DEPTH = 3
PARTIAL_DOWNLOADS = (".crdownload", ".download", ".part", ".partial", ".tmp")
INSTALLERS = (".dmg", ".pkg", ".app", ".mpkg", ".exe", ".msi", ".msix", ".appx")
WATCH_SECONDS = 3
_put_back: set[str] = set()  # files just restored by undo


class TidyError(Exception):
    pass


def _came_from(path: Path) -> str:
    """Source website of a download (Spotlight on macOS, Zone.Identifier on Windows)."""
    if WINDOWS:
        try:
            with open(f"{path}:Zone.Identifier", encoding="utf-8", errors="ignore") as stream:
                lines = dict(line.strip().split("=", 1) for line in stream if "=" in line)
        except OSError:
            return ""
        return urlparse(lines.get("ReferrerUrl") or lines.get("HostUrl") or "").netloc
    try:
        output = subprocess.run(["mdls", "-raw", "-name", "kMDItemWhereFroms", str(path)],
                                capture_output=True, text=True, timeout=3).stdout
    except subprocess.TimeoutExpired:
        return ""
    domains = [urlparse(url).netloc for url in output.split('"')[1::2]]
    domains = [d for d in domains if d]
    return domains[-1] if domains else ""


def _folders() -> list[str]:
    """User folders up to 3 levels deep, relative to home, breadth-first."""
    found = []
    level = [(root, 0) for root in DESTINATION_ROOTS if root.is_dir()]
    while level and len(found) < MAX_FOLDERS:
        below = []
        for folder, depth in level:
            if len(found) >= MAX_FOLDERS:
                break
            root = depth == 0
            # Documents and Desktop are valid targets; cloud-drive roots are not.
            if _visible(folder) and (not root or folder in (HOME / "Documents", HOME / "Desktop")):
                found.append(folder.relative_to(HOME).as_posix())
            if depth >= FOLDER_DEPTH or (folder / ".git").exists():
                continue  # skip code projects
            try:
                children = sorted(p for p in folder.iterdir() if p.is_dir())
            except OSError:
                continue
            below += [(c, depth + 1) for c in children
                      if not c.name.startswith(".") and c.name not in SKIP_PARTS and not c.name.endswith("_files")]
        level = below
    return sorted(found)


def _downloaded_files() -> list[Path]:
    """Finished downloads directly in Downloads."""
    return [p for p in DOWNLOADS.iterdir()
            if p.is_file() and not p.name.startswith(".") and not p.name.endswith(PARTIAL_DOWNLOADS)]


SAYS_CHARS = 300


def _says(path: Path) -> str:
    """Start of a file's text, or ""."""
    if WINDOWS:
        from dock_agent.win import reading
    else:
        from dock_agent import reading
    try:
        return " ".join(reading.file_text(str(path))[:SAYS_CHARS * 2].split())[:SAYS_CHARS]
    except Exception:
        return ""


def overview() -> dict:
    files = _downloaded_files()
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "files": [
            {"name": p.name, "changed": _when(p), "size_kb": p.stat().st_size // 1024, "from": _came_from(p),
             "says": _says(p)}
            for p in files[:MAX_FILES]
        ],
        "total_files": len(files),
        "folders": _folders(),
    }


def _destination(to: str, new_folder: bool) -> Path:
    folder = Path(to).expanduser()
    folder = folder if folder.is_absolute() else HOME / folder
    folder = folder.resolve()
    if not _visible(folder):
        raise TidyError(f"I can only move files into your own folders, not {to}.")
    if folder.is_dir():
        return folder
    if new_folder and folder.parent.is_dir() and _visible(folder.parent):
        folder.mkdir()
        return folder
    raise TidyError(f"The folder {to} doesn't exist.")


def _free_name(folder: Path, name: str) -> Path:
    """A free destination path, adding " (2)" etc. if needed."""
    target = folder / name
    stem, suffix, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def move(moves: list[dict]) -> dict:
    moved, problems, undo = [], [], []
    for item in moves:
        name = Path(item.get("file", "")).name
        source = DOWNLOADS / name
        try:
            if not name or not source.is_file():
                raise TidyError(f"{name or 'That file'} isn't in Downloads.")
            folder = _destination(item.get("to", ""), bool(item.get("new_folder")))
            target = _free_name(folder, name)
            shutil.move(str(source), str(target))
            undo.append([str(target), str(source)])
            moved.append({"file": name, "to": folder.relative_to(HOME).as_posix()})
        except (TidyError, OSError) as e:
            problems.append(f"{name}: {e}")
    if undo:
        UNDO_FILE.parent.mkdir(parents=True, exist_ok=True)
        UNDO_FILE.write_text(json.dumps(undo))
    return {"moved": moved, "problems": problems}


def undo() -> dict:
    if not UNDO_FILE.exists():
        raise TidyError("There's nothing to undo.")
    restored = []
    for target, source in json.loads(UNDO_FILE.read_text()):
        if Path(target).exists() and not Path(source).exists():
            _put_back.add(Path(source).name)
            shutil.move(target, source)
            restored.append(Path(source).name)
    UNDO_FILE.unlink()
    return {"restored": restored}


def watch_downloads() -> None:
    """Poll Downloads and report new files once their size stops changing."""
    threading.Thread(target=_watch, daemon=True).start()


def _sizes() -> dict[str, int]:
    try:
        return {p.name: p.stat().st_size for p in _downloaded_files()}
    except OSError:
        return {}


def _watch() -> None:
    known = set(_sizes())
    waiting: dict[str, int] = {}
    while True:
        time.sleep(WATCH_SECONDS)
        sizes = _sizes()
        known &= set(sizes)
        for name, size in sizes.items():
            if name in known:
                continue
            if name in _put_back:
                _put_back.discard(name)
                known.add(name)
                continue
            if waiting.get(name) != size:
                waiting[name] = size
                continue
            known.add(name)
            waiting.pop(name, None)
            if name.lower().endswith(INSTALLERS) or size == 0:
                continue
            path = DOWNLOADS / name
            try:
                link.send_event("new_download", file=name, path=str(path), came_from=_came_from(path),
                                size_kb=size // 1024, folders=_folders())
            except Exception as e:
                print(f"Couldn't announce the download {name}: {e!r}")
        for name in list(waiting):
            if name not in sizes:
                waiting.pop(name)
