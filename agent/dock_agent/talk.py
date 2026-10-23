"""Talking to Dock on the Mac: the talk key or a click on the menu bar face opens the
chat box and starts listening. Speech is transcribed locally (speech.py).
"""

import threading

from PyObjCTools import AppHelper

from dock_agent import bubble, files, hotkey, menubar, menus, speech, voice_out

_listener = None
_listening = False


def start() -> bool:
    """Main thread. False if the talk key couldn't be registered."""
    # Run after the key event; the chat box can't take focus from inside it.
    return hotkey.start(lambda: AppHelper.callAfter(tap))


def tap() -> None:
    """Talk key or face click (main thread): send, close, stop speaking, or start listening."""
    if _listening and _listener.talked():
        _released()
    elif _listening or bubble.composing():
        cancel()
        bubble.compose(False)
    elif voice_out.speaking():
        voice_out.stop()
    elif not bubble.just_closed():
        toggle()  # listen first, or the chat box misses the typing
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
        _pressed(on_pause=lambda: AppHelper.callAfter(_released))


def listening() -> bool:
    return _listening


def cancel() -> None:
    """Cancel listening without sending."""
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
        bubble.call("showAnswer('', 'Allow the microphone for OneDock, then try again.'); hideLater($('answer'), 8000, { everywhere: false })")
        return
    try:
        _listener = _listener or speech.Listener()
        _listener.start(hints=_hints(), on_pause=on_pause)
    except Exception as e:
        print(f"Couldn't start listening: {e!r}")
        bubble.call("showAnswer('', \"The microphone didn't start. Check System Settings › Privacy › Microphone.\"); "
                    "hideLater($('answer'), 8000, { everywhere: false })")
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
