"""On-screen pointer: a transparent, click-through window with a highlight, arrow and label.

Hidden on any user input or after SHOW_SECONDS. Runs on the main thread via AppHelper.callAfter.
"""

import math
import time

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventMaskLeftMouseDown,
    NSEventMaskMouseMoved,
    NSEventMaskOtherMouseDown,
    NSEventMaskRightMouseDown,
    NSEventMaskScrollWheel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMakePoint,
    NSMakeRect,
    NSScreen,
    NSScreenSaverWindowLevel,
    NSString,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from PyObjCTools import AppHelper

SHOW_SECONDS = 6
IGNORE_FIRST_SECONDS = 0.5
MOVE_PIXELS = 25
MARGIN = 360
LABEL_START = 200

_window = None
_shown = 0  # so an old timer doesn't hide a newer pointer
_monitor = None


def start_app() -> None:
    """Set up AppKit as a background app. Main thread."""
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def run() -> None:
    """Run the AppKit event loop until Ctrl+C."""
    AppHelper.runEventLoop(installInterrupt=True)


def show(rect: tuple[float, float, float, float], label: str, on_hide=None) -> None:
    """Point at `rect` (x, y, width, height, top-left origin). Thread-safe."""
    AppHelper.callAfter(_show, rect, label, on_hide)


def hide() -> None:
    AppHelper.callAfter(_hide)


class PointerView(NSView):

    def isFlipped(self):
        return True

    def drawRect_(self, _dirty):
        orange = NSColor.systemOrangeColor()
        x, y, w, h = self.target

        box = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x - 4, y - 4, w + 8, h + 8), 6, 6)
        orange.colorWithAlphaComponent_(0.18).setFill()
        box.fill()
        box.setLineWidth_(4)
        orange.setStroke()
        box.stroke()

        # Arrow from below for menu bar titles, from the right for menu items (left near the edge).
        side = -1 if self.flipped else 1
        if y < 40:
            head = (x + w / 2, y + h + 8)
            tail = (head[0] + side * 90, head[1] + 130)
        else:
            head = (x + w + 10, y + h / 2) if side == 1 else (x - 10, y + h / 2)
            tail = (head[0] + side * 150, head[1] + 70)
        for color, width in ((NSColor.whiteColor(), 11), (orange, 6)):
            _draw_arrow(head, tail, color, width)

        attributes = _label_attributes()
        text = NSString.stringWithString_(self.label)
        size = text.sizeWithAttributes_(attributes)
        start = tail[0] - 12 if side == 1 else tail[0] - size.width - 12
        bubble = NSMakeRect(start, tail[1], size.width + 24, size.height + 14)
        orange.setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bubble, 10, 10).fill()
        text.drawAtPoint_withAttributes_(NSMakePoint(start + 12, tail[1] + 7), attributes)


def _label_attributes() -> dict:
    return {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(20),
        NSForegroundColorAttributeName: NSColor.whiteColor(),
    }


def _draw_arrow(head, tail, color, width) -> None:
    angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
    path = NSBezierPath.bezierPath()
    path.setLineWidth_(width)
    path.setLineCapStyle_(1)
    path.setLineJoinStyle_(1)
    path.moveToPoint_(NSMakePoint(*tail))
    path.lineToPoint_(NSMakePoint(*head))
    for side in (-1, 1):
        wing = angle + math.pi - side * 0.5
        path.moveToPoint_(NSMakePoint(*head))
        path.lineToPoint_(NSMakePoint(head[0] + 22 * math.cos(wing), head[1] + 22 * math.sin(wing)))
    color.setStroke()
    path.stroke()


def _show(rect, label, on_hide) -> None:
    global _window, _shown
    _hide()
    _shown += 1
    shown = _shown

    x, y, w, h = rect
    # Size the window to fit long labels.
    label_width = NSString.stringWithString_(label).sizeWithAttributes_(_label_attributes()).width
    room = max(MARGIN, LABEL_START + label_width + 60)
    screens = [f for f in (screen.frame() for screen in NSScreen.screens()) if f.origin.x <= x < f.origin.x + f.size.width]
    right_edge = (screens[0].origin.x + screens[0].size.width) if screens else x + w + room
    flipped = x + w + room > right_edge
    left, top = (x - room if flipped else x - 40), y - 40
    width, height = w + room + 40, h + 260
    # AppKit uses a bottom-left origin.
    screen_height = NSScreen.screens()[0].frame().size.height
    frame = NSMakeRect(left, screen_height - top - height, width, height)

    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setHasShadow_(False)
    window.setIgnoresMouseEvents_(True)
    window.setLevel_(NSScreenSaverWindowLevel)
    window.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary
        | NSWindowCollectionBehaviorStationary
    )
    view = PointerView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    view.target = (x - left, y - top, w, h)
    view.flipped = flipped
    view.label = label
    window.setContentView_(view)
    window.orderFrontRegardless()
    _window = window
    _watch_user(time.time())

    def finish():
        if shown == _shown:
            _hide()
            if on_hide:
                on_hide()

    AppHelper.callLater(SHOW_SECONDS, finish)


def _watch_user(shown_at: float) -> None:
    """Hide on click, key press, scroll or mouse move."""
    global _monitor
    start = NSEvent.mouseLocation()

    def handle(event):
        if time.time() - shown_at < IGNORE_FIRST_SECONDS:
            return
        if event.type() == 5:
            now = NSEvent.mouseLocation()
            if math.hypot(now.x - start.x, now.y - start.y) < MOVE_PIXELS:
                return
        # Leave any menu Dock opened; the timer closes it later.
        _hide()

    mask = (NSEventMaskMouseMoved | NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown
            | NSEventMaskOtherMouseDown | NSEventMaskScrollWheel | NSEventMaskKeyDown)
    _monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, handle)


def _hide() -> None:
    global _window, _monitor
    if _monitor is not None:
        NSEvent.removeMonitor_(_monitor)
        _monitor = None
    if _window is not None:
        _window.orderOut_(None)
        _window = None
