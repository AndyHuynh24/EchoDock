"""Talking to Dock on Windows: the talk key or a tray click opens the chat box and
starts listening. Speech is transcribed locally (speech.py).
"""

import threading

from dock_agent import files, speech
from dock_agent.win import bubble, hotkey, menus, tray, voice_out

_listener = None
_listening = False


def start() -> bool:
    return hotkey.start(tap)


def tap() -> None:
    """Talk key or tray click: send, stop speaking, or start listening."""
    if _listening:
        _released()
    elif voice_out.speaking():
        voice_out.stop()
    elif not bubble.just_closed():
        toggle()
        bubble.compose(True)


def _hints() -> list[str]:
    """Hints: folder names, then the front app's menu items."""
    hints = files.spoken_folder_names()[:12]
    try:
        _, pid = menus.front_app()
        cached = menus._cache.get(pid)
        if cached:
            hints += list(dict.fromkeys(item["path"][-1] for item in cached[1]))[:8]
    except Exception:
        pass
    return hints


def toggle() -> None:
    """Chat box mic button: start listening, or send."""
    if _listening:
        _released()
    else:
        _pressed(on_pause=_released)


def listening() -> bool:
    return _listening


def cancel() -> None:
    """Cancel listening without sending."""
    global _listening
    if not _listening:
        return
    _listening = False
    _listener.cancel()
    tray.set_listening(False)
    bubble.call("macMic(false)")
    bubble.listening(None)
    print("Stopped listening (cancelled)")


def _pressed(on_pause=None) -> None:
    global _listener, _listening
    voice_out.stop()
    if speech.permissions()["microphone"] != "allowed":
        speech.ask_permission()
        bubble.call("showAnswer('', 'Let apps use your microphone in Windows Settings, then try again.'); hideLater($('answer'), 8000)")
        return
    try:
        _listener = _listener or speech.Listener()
        _listener.start(hints=_hints(), on_pause=(lambda: threading.Thread(target=on_pause, daemon=True).start()) if on_pause else None)
    except Exception as e:
        print(f"Couldn't start listening: {e!r}")
        bubble.call("showAnswer('', \"The microphone didn't start. Check Settings › Privacy & security › Microphone.\"); "
                    "hideLater($('answer'), 8000)")
        return
    _listening = True
    tray.set_listening(True)
    bubble.listening("")
    bubble.call("macMic(true)")


def _released() -> None:
    global _listening
    if not _listening:
        return
    _listening = False
    tray.set_listening(False)
    bubble.call("macMic(false)")

    def finish():
        try:
            text = _listener.stop()
        except Exception as e:
            print(f"Couldn't turn speech into text: {e!r}")
            text = ""
        print(f"Heard: {text!r}")
        bubble.ask(text)

    threading.Thread(target=finish, daemon=True).start()
