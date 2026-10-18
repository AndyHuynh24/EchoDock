"""The talk key: press Option+Space once anywhere to talk to Dock (like tapping
the face on the phone): the chat box opens and Dock listens. Press it again to
send right away (it also sends by itself when you stop talking).

A macOS event tap sees the key before the app in front does and swallows it,
so it doesn't type a space into your document. It needs the same
Accessibility permission Dock already uses. Runs on the main thread's run loop.

Windows: a low-level keyboard hook (SetWindowsHookEx WH_KEYBOARD_LL) does the same (docs/WINDOWS-PORT.md).
"""

from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetMain,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

SPACE = 49
KEY_NAME = "⌥ Space"

_tap = None
_down = False  # Space is down as part of the talk key (so its repeats and key-up are swallowed too)


def start(on_tap) -> bool:
    """Call on_tap() each time the key is pressed.
    Returns False if macOS didn't allow it (no Accessibility permission yet)."""
    global _tap

    def callback(proxy, kind, event, refcon):
        global _down
        if kind in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(_tap, True)  # macOS turns slow taps off; turn it back on
            return event
        if CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode) != SPACE:
            return event
        if kind == kCGEventKeyDown:
            if _down:
                return None  # the key repeating while held
            flags = CGEventGetFlags(event)
            if flags & kCGEventFlagMaskAlternate and not flags & (kCGEventFlagMaskCommand | kCGEventFlagMaskControl):
                _down = True
                on_tap()
                return None
        elif kind == kCGEventKeyUp and _down:
            _down = False
            return None
        return event

    mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
    _tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault, mask, callback, None)
    if _tap is None:
        return False
    CFRunLoopAddSource(CFRunLoopGetMain(), CFMachPortCreateRunLoopSource(None, _tap, 0), kCFRunLoopCommonModes)
    CGEventTapEnable(_tap, True)
    return True
