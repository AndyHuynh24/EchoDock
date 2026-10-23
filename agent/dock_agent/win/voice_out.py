"""Spoken replies on Windows with SAPI, on its own COM thread."""

import queue
import threading
import winsound

SPEAK_ASYNC, PURGE = 1, 2

_jobs: queue.Queue = queue.Queue()
_speaking = threading.Event()
_said = 0  # so an old "done" doesn't fire for a newer request
_lock = threading.Lock()


def _run() -> None:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    current = None
    while True:
        try:
            job = _jobs.get(timeout=0.1)
        except queue.Empty:
            job = None
        if job is not None:
            kind, number, text, done = job
            voice.Speak("", SPEAK_ASYNC | PURGE)
            current = None
            _speaking.clear()
            if kind == "say" and text:
                voice.Speak(text, SPEAK_ASYNC | PURGE)
                current = (number, done)
                _speaking.set()
            continue
        if current is not None and voice.WaitUntilDone(0):
            number, done = current
            current = None
            _speaking.clear()
            if done and number == _said:
                threading.Thread(target=done, daemon=True).start()


threading.Thread(target=_run, daemon=True, name="voice").start()


def say(text: str, done=None) -> None:
    """Speak `text`, interrupting anything playing. done() runs at the end."""
    global _said
    with _lock:
        _said += 1
        _jobs.put(("say", _said, text, done))
    _speaking.set()


def speaking() -> bool:
    return _speaking.is_set()


def stop() -> None:
    global _said
    with _lock:
        _said += 1
        _jobs.put(("stop", _said, "", None))
    _speaking.clear()


def done_sound() -> None:
    """Play the short "done" sound."""
    winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
