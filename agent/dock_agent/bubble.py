"""Dock's windows on the Mac, so Dock works without a phone:

- the bubble: a small floating panel under the menu bar (top right) that
  shows Dock's cards: answers, "Put it in …?", "Save it in …?" and so on. It
  is the phone app's own page in "Mac" mode, so every card and button works
  the same in both places. It never takes the focus away from your app, so
  "Save here" still works while a Save window is open.
- the chat box: clicking the face in the menu bar opens a "Ask Dock…" box
  (and a microphone button) at the top of the bubble. Only then can the
  bubble take the keyboard; it closes when you click elsewhere or press Esc.
- the welcome window: the setup page (permissions, AI, try it, add a phone).

The page talks to this file through window.webkit.messageHandlers.dock:
{"show": bool, "height": px}, {"say": text}, {"focus": "24:59" or ""},
{"listen": "toggle"} (the chat box's microphone) or {"listen": "cancel"},
{"hush": true} (stop talking), {"sound": "done"}, {"compose": false} (closed),
{"settings": true} (the chat box's gear: open the Dock window).

Windows: a WebView2 window (e.g. via pywebview) can show the same page (docs/WINDOWS-PORT.md).
"""

import json
import os
import time
from urllib.parse import quote

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled,
)
from Foundation import NSURL, NSObject, NSURLRequest
from PyObjCTools import AppHelper
from WebKit import WKWebsiteDataStore, WKWebView, WKWebViewConfiguration

from dock_agent import voice_out

WIDTH = 400
GAP = 8  # from the menu bar and the screen edge

_panel = None
_view = None
_welcome = None
_composing = False
_ready = False    # the page has loaded and can show the chat box
_closed_at = 0.0  # when the chat box last closed by itself (clicking the face then shouldn't reopen it)
on_focus = None   # set by main.py: gets the focus countdown text for the menu bar
on_listen = None  # set by main.py: the chat box's microphone button (talk.toggle)
on_cancel = None  # set by main.py: stop listening without sending (talk.cancel)


class BubblePanel(NSPanel):
    """Takes the keyboard only while the chat box is open, so clicking a card's
    button never takes the focus away from the user's app (e.g. a Save window)."""

    def canBecomeKeyWindow(self):
        return _composing


class Loader(NSObject, protocols=[objc.protocolNamed("WKNavigationDelegate")]):
    """If the page can't load yet (the server is still starting), try again."""

    def webView_didFailProvisionalNavigation_withError_(self, view, navigation, error):
        print(f"Bubble page didn't load yet ({error.localizedDescription()}); trying again")
        AppHelper.callLater(2, _load)

    def webView_didFailNavigation_withError_(self, view, navigation, error):
        print(f"Bubble page failed ({error.localizedDescription()}); trying again")
        AppHelper.callLater(2, _load)

    def webViewWebContentProcessDidTerminate_(self, view):
        print("Bubble page stopped; loading it again")
        AppHelper.callLater(1, _load)


_loader = Loader.alloc().init()


class Watcher(NSObject):
    def windowDidResignKey_(self, notification):
        global _closed_at
        if _composing:  # clicked somewhere else (or on the face again): close the chat box
            compose(False)
            _closed_at = time.time()


_watcher = Watcher.alloc().init()


def _server() -> str:
    return os.environ.get("DOCK_SERVER", "ws://localhost:8000").replace("ws", "http", 1).rstrip("/")


class Bridge(NSObject, protocols=[objc.protocolNamed("WKScriptMessageHandler")]):
    """Messages from the bubble's page."""

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        data = dict(message.body())
        if "show" in data:
            _place(bool(data["show"]), float(data.get("height") or 0))
        if "say" in data:
            voice_out.say(str(data["say"]), done=lambda: call("speechDone()"))
        if "focus" in data and on_focus:
            on_focus(str(data["focus"]))
        if data.get("listen") == "cancel":
            if on_cancel:
                on_cancel()
        elif data.get("listen") and on_listen:
            on_listen()
        if data.get("hush"):
            voice_out.stop()
        if data.get("sound") == "done":
            voice_out.done_sound()
        if data.get("compose") is False and _composing:
            compose(False)
        if data.get("settings"):
            compose(False)
            show_welcome()
        if data.get("ready"):
            global _ready
            _ready = True
            print("Bubble page ready")


_bridge = Bridge.alloc().init()


def start() -> None:
    """Create the bubble (hidden until there's a card). Main thread."""
    global _panel, _view
    config = WKWebViewConfiguration.alloc().init()
    # Nothing saved between starts: no stale copy of the page (or its offline helper) is ever used.
    config.setWebsiteDataStore_(WKWebsiteDataStore.nonPersistentDataStore())
    config.userContentController().addScriptMessageHandler_name_(_bridge, "dock")
    _view = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, WIDTH, 120), config)
    _view.setValue_forKey_(False, "drawsBackground")  # see-through around the cards

    _panel = BubblePanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, WIDTH, 120), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, False)
    _panel.setOpaque_(False)
    _panel.setBackgroundColor_(NSColor.clearColor())
    _panel.setHasShadow_(False)
    _panel.setLevel_(NSStatusWindowLevel)
    _panel.setHidesOnDeactivate_(False)
    _panel.setBecomesKeyOnlyIfNeeded_(True)
    _panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
    _panel.setContentView_(_view)
    _panel.setDelegate_(_watcher)

    _view.setNavigationDelegate_(_loader)
    _load()


def _load() -> None:
    global _ready
    _ready = False
    print("Loading the bubble page")
    token = quote(os.environ.get("DOCK_TOKEN", ""))
    _view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(f"{_server()}/?token={token}&screen=mac")))


def _place(show: bool, height: float) -> None:
    if not show or height <= 0:
        _panel.orderOut_(None)
        return
    area = NSScreen.mainScreen().visibleFrame()  # below the menu bar
    height = min(height, area.size.height * 0.8)
    x = area.origin.x + area.size.width - WIDTH - GAP
    y = area.origin.y + area.size.height - height - GAP
    _panel.setFrame_display_(NSMakeRect(x, y, WIDTH, height), True)
    _panel.orderFrontRegardless()


def compose(open_it: bool | None = None) -> None:
    """Open or close the chat box (None: switch). Main thread."""
    global _composing
    if open_it is None and not _composing and time.time() - _closed_at < 0.4:
        return  # this click on the face is what just closed it
    if not _ready and not _composing:
        _load()  # (the page isn't there yet: never take the keyboard for an empty box)
        return
    _composing = (not _composing) if open_it is None else open_it
    call(f"macCompose({'true' if _composing else 'false'})")
    if _composing:
        _panel.makeKeyAndOrderFront_(None)
        _panel.makeFirstResponder_(_view)
    elif _panel.isKeyWindow():
        # Give the keyboard back to the user's app; the page shows the bubble
        # again if cards are still on it.
        _panel.orderOut_(None)
        call("tellBubble.last = null; tellBubble()")


def just_closed() -> bool:
    """Did the chat box close by itself a moment ago (so this click on the face is what closed it)?"""
    return not _composing and time.time() - _closed_at < 0.4


def has_keyboard() -> bool:
    """Is the chat box open and taking the keyboard?"""
    return _composing and _panel is not None and _panel.isKeyWindow()


def call(script: str) -> None:
    """Run JavaScript in the bubble's page. Safe from any thread."""
    AppHelper.callAfter(lambda: _view.evaluateJavaScript_completionHandler_(script, None))


def listening(words: str | None) -> None:
    """Show "Listening…" (and the words so far), or None to stop showing it."""
    call(f"macListening({json.dumps(words)})")


def ask(text: str) -> None:
    """Send what the user said to Dock; the answer appears in the bubble and is spoken."""
    call(f"macAsk({json.dumps(text)})")


def show_welcome(part: str = "") -> None:
    """Open the welcome/setup window (part="phone" jumps to adding a phone). Main thread."""
    global _welcome
    if _welcome is None:
        _welcome = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 720, 820), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
        _welcome.setTitle_("Dock")
        _welcome.setReleasedWhenClosed_(False)
        config = WKWebViewConfiguration.alloc().init()
        config.setWebsiteDataStore_(WKWebsiteDataStore.nonPersistentDataStore())
        _welcome.setContentView_(WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 720, 820), config))
        _welcome.center()
    url = f"{_server()}/setup?app=1" + (f"#{part}" if part else "")
    _welcome.contentView().loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))
    NSApp.activateIgnoringOtherApps_(True)
    _welcome.makeKeyAndOrderFront_(None)
