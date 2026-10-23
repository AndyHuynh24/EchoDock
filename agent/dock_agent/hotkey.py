"""Global talk key (Option+Space) using a macOS event tap. Needs Accessibility."""

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
_down = False


def start(on_tap) -> bool:
    """Call on_tap() on each press. Returns False without Accessibility permission."""
    global _tap

    def callback(proxy, kind, event, refcon):
        global _down
        if kind in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(_tap, True)  # macOS disables slow taps; re-enable
            return event
        if CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode) != SPACE:
            return event
        if kind == kCGEventKeyDown:
            if _down:
                return None
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
