"""Dock's spoken replies on the Mac, with macOS's own voice (`say`).

Windows: System.Speech / Windows.Media.SpeechSynthesis (docs/WINDOWS-PORT.md).
"""

import subprocess
import threading

_process: subprocess.Popen | None = None
_lock = threading.Lock()


def say(text: str, done=None) -> None:
    """Speak `text` (stopping anything still being said). done() runs when it ends."""
    global _process
    stop()
    with _lock:
        _process = subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process = _process

    def wait():
        process.wait()
        if done and process is _process:
            done()

    threading.Thread(target=wait, daemon=True).start()


def speaking() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def done_sound() -> None:
    """A short sound for "done", instead of saying it."""
    from AppKit import NSSound
    NSSound.soundNamed_("Pop").play()


def stop() -> None:
    with _lock:
        if _process is not None and _process.poll() is None:
            _process.terminate()
