"""Talking to Dock on Windows: press the talk key once (hotkey.py) or click the
tray icon, like tapping the face on the phone (the same as dock_agent/talk.py
on the Mac). The chat box opens and Dock listens ("Listening…", the tray icon
turns cyan); type instead and it stops listening. When you stop talking (or
press the key again) Whisper turns your words into text on this computer
(speech.py, shared with the Mac), and the bubble's page sends them to Dock and
speaks the answer.
"""

import threading

from dock_agent import files, speech
from dock_agent.win import bubble, hotkey, menus, tray, voice_out

_listener = None
_listening = False


def start() -> bool:
    return hotkey.start(tap)


def tap() -> None:
    """The talk key or a click on the tray icon. Listening: send what was said
    now. Talking: be quiet. Otherwise open the chat box and listen."""
    if _listening:
        _released()
    elif voice_out.speaking():
        voice_out.stop()
    elif not bubble.just_closed():  # (a click on the tray icon that just closed the chat box)
        toggle()  # (listen first, then open the chat box: the same order as on the Mac)
        bubble.compose(True)


def _hints() -> list[str]:
    """Words to expect: the user's folder names, then the front app's menu items (already read, so quick)."""
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
    """The microphone button in the chat box: start listening, or send what was said."""
    if _listening:
        _released()
    else:
        _pressed(on_pause=_released)


def listening() -> bool:
    return _listening


def cancel() -> None:
    """Clicked again while listening: stop, and send nothing."""
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
