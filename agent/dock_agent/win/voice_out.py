"""Dock's spoken replies on Windows, with Windows' own voice (SAPI, the voice
in Settings › Time & language › Speech). The same as dock_agent/voice_out.py
on the Mac: say(), speaking(), stop() and a short "done" sound.

The voice lives on its own thread (it's COM), and say/stop hand it work.
"""

import queue
import threading
import winsound

SPEAK_ASYNC, PURGE = 1, 2

_jobs: queue.Queue = queue.Queue()
_speaking = threading.Event()
_said = 0  # counts requests, so an old "done" doesn't run for a newer one
_lock = threading.Lock()


def _run() -> None:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    current = None  # (number, done) being spoken
    while True:
        try:
            job = _jobs.get(timeout=0.1)
        except queue.Empty:
            job = None
        if job is not None:
            kind, number, text, done = job
            voice.Speak("", SPEAK_ASYNC | PURGE)  # (stops whatever was being said)
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
    """Speak `text` (stopping anything still being said). done() runs when it ends."""
    global _said
    with _lock:
        _said += 1
        _jobs.put(("say", _said, text, done))
    _speaking.set()  # (right away, so speaking() is true from now on)


def speaking() -> bool:
    return _speaking.is_set()


def stop() -> None:
    global _said
    with _lock:
        _said += 1
        _jobs.put(("stop", _said, "", None))
    _speaking.clear()


def done_sound() -> None:
    """A short sound for "done", instead of saying it."""
    winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
