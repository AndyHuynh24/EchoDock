"""Talking to Dock on the Mac: press the talk key once (hotkey.py) or click
Dock's face in the menu bar, like tapping the face on the phone. The chat box
opens and Dock listens ("Listening…", the menu bar face turns cyan); type
instead and it stops listening. When you stop talking (or press the key again)
Whisper turns your words into text on this Mac (speech.py), and the bubble's
page sends them to Dock and speaks the answer (bubble.py, voice_out.py).
"""

import threading

from PyObjCTools import AppHelper

from dock_agent import bubble, files, hotkey, menubar, menus, speech, voice_out

_listener = None
_listening = False


def start() -> bool:
    """Main thread. False if the talk key couldn't be set up (no Accessibility yet)."""
    # (Run just after the key event, not inside it: from inside, the chat box
    # can't take the keyboard.)
    return hotkey.start(lambda: AppHelper.callAfter(tap))


def tap() -> None:
    """The talk key or a click on the face (main thread). Listening: send what
    was said now. Talking: be quiet. Otherwise open the chat box and listen."""
    if _listening:
        _released()
    elif voice_out.speaking():
        voice_out.stop()
    elif not bubble.just_closed():  # (a click on the face that just closed the chat box)
        toggle()  # (listen first: the other way round, the chat box doesn't get the typing)
        bubble.compose(True)


def _hints() -> list[str]:
    """Words to expect: the user's folder names, then the front app's menu items (already read, so quick)."""
    hints = files.spoken_folder_names()[:12]  # (short: long hints make Whisper invent lists)
    try:
        _, pid = menus.front_app()
        cached = menus._cache.get(pid)
        if cached:
            hints += list(dict.fromkeys(item["path"][-1] for item in cached[1]))[:8]
    except Exception:
        pass
    return hints


def toggle() -> None:
    """The microphone button in the chat box: start listening, or send what was
    said. It also sends by itself once the user stops talking."""
    if _listening:
        _released()
    else:
        _pressed(on_pause=lambda: AppHelper.callAfter(_released))


def listening() -> bool:
    return _listening


def cancel() -> None:
    """Clicked again while listening: stop, and send nothing."""
    global _listening
    if not _listening:
        return
    _listening = False
    _listener.cancel()
    menubar.set_listening(False)
    bubble.call("macMic(false)")
    bubble.listening(None)
    print("Stopped listening (cancelled)")


def _pressed(on_pause=None) -> None:
    global _listener, _listening
    voice_out.stop()
    if speech.permissions()["microphone"] != "allowed":
        speech.ask_permission()
        bubble.call("showAnswer('', 'Allow the microphone for OneDock, then try again.'); hideLater($('answer'), 8000)")
        return
    try:
        _listener = _listener or speech.Listener()
        _listener.start(hints=_hints(), on_pause=on_pause)
    except Exception as e:
        print(f"Couldn't start listening: {e!r}")
        bubble.call("showAnswer('', \"The microphone didn't start. Check System Settings › Privacy › Microphone.\"); "
                    "hideLater($('answer'), 8000)")
        return
    _listening = True
    menubar.set_listening(True)
    bubble.listening("")
    bubble.call("macMic(true)")


def _released() -> None:
    global _listening
    if not _listening:
        return
    _listening = False
    menubar.set_listening(False)
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
