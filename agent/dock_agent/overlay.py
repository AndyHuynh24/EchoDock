"""The on-screen pointer: a see-through, click-through window that draws a
highlight box, an arrow and a label next to a spot on the screen.

It goes away as soon as you do something (click, type, scroll, or move the
mouse a little), so it never stays on screen while you're already busy with
something else. Otherwise it goes after SHOW_SECONDS.

AppKit windows must be created on the main thread, so the agent runs the
AppKit event loop on the main thread (see main.py) and `show`/`hide` hand
their work to it with AppHelper.callAfter."""

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
IGNORE_FIRST_SECONDS = 0.5  # right after it appears, don't count small jitters
MOVE_PIXELS = 25           # moving the mouse further than this hides it
MARGIN = 360  # room around the target for the arrow and a short label
LABEL_START = 200  # how far from the target the label starts (see drawRect_)

_window = None
_shown = 0  # counts shows, so an old timer doesn't hide a newer pointer
_monitor = None  # watches the mouse and keyboard while the pointer is shown


def start_app() -> None:
    """Set up AppKit for a background helper (no Dock icon). Call on the main thread."""
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def run() -> None:
    """Run the AppKit event loop on the main thread until Ctrl+C."""
    AppHelper.runEventLoop(installInterrupt=True)


def show(rect: tuple[float, float, float, float], label: str, on_hide=None) -> None:
    """Point at `rect` (x, y, width, height from the top-left of the main screen).
    Safe to call from any thread."""
    AppHelper.callAfter(_show, rect, label, on_hide)


def hide() -> None:
    AppHelper.callAfter(_hide)


class PointerView(NSView):
    """Draws the highlight, arrow and label. Uses top-left coordinates."""

    def isFlipped(self):
        return True

    def drawRect_(self, _dirty):
        orange = NSColor.systemOrangeColor()
        x, y, w, h = self.target

        # Highlight box around the target.
        box = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x - 4, y - 4, w + 8, h + 8), 6, 6)
        orange.colorWithAlphaComponent_(0.18).setFill()
        box.fill()
        box.setLineWidth_(4)
        orange.setStroke()
        box.stroke()

        # Arrow: from below for menu bar titles, from the right for menu items.
        # Near the right edge of the screen, the arrow and label go on the left.
        side = -1 if self.flipped else 1
        if y < 40:
            head = (x + w / 2, y + h + 8)
            tail = (head[0] + side * 90, head[1] + 130)
        else:
            head = (x + w + 10, y + h / 2) if side == 1 else (x - 10, y + h / 2)
            tail = (head[0] + side * 150, head[1] + 70)
        for color, width in ((NSColor.whiteColor(), 11), (orange, 6)):
            _draw_arrow(head, tail, color, width)

        # Label bubble at the arrow's tail.
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
    path.setLineCapStyle_(1)  # round
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
    # Long labels ("Show Downloads  ⌥⌘L") need a wider window, or they get cut off.
    label_width = NSString.stringWithString_(label).sizeWithAttributes_(_label_attributes()).width
    room = max(MARGIN, LABEL_START + label_width + 60)
    # Not enough room right of the target on its screen? Put the arrow and label on the left.
    screens = [f for f in (screen.frame() for screen in NSScreen.screens()) if f.origin.x <= x < f.origin.x + f.size.width]
    right_edge = (screens[0].origin.x + screens[0].size.width) if screens else x + w + room
    flipped = x + w + room > right_edge
    # The window covers the target plus room for the arrow and label.
    left, top = (x - room if flipped else x - 40), y - 40
    width, height = w + room + 40, h + 260
    # AppKit measures windows from the bottom-left of the main screen.
    screen_height = NSScreen.screens()[0].frame().size.height
    frame = NSMakeRect(left, screen_height - top - height, width, height)

    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    window.setOpaque_(False)
    window.setBackgroundColor_(NSColor.clearColor())
    window.setHasShadow_(False)
    window.setIgnoresMouseEvents_(True)
    window.setLevel_(NSScreenSaverWindowLevel)  # above open menus
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
    """Hide the pointer as soon as the user clicks, types, scrolls or moves the mouse."""
    global _monitor
    start = NSEvent.mouseLocation()

    def handle(event):
        if time.time() - shown_at < IGNORE_FIRST_SECONDS:
            return
        if event.type() == 5:  # mouse moved: only count a real move, not a nudge
            now = NSEvent.mouseLocation()
            if math.hypot(now.x - start.x, now.y - start.y) < MOVE_PIXELS:
                return
        # Only the pointer goes now. A menu Dock opened stays open for the user to
        # click; if they don't, the timer below still closes it.
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
