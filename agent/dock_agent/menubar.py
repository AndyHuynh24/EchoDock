"""Dock's icon in the Mac menu bar: a small face (cyan while listening) and
the focus countdown next to it. Click it for the chat box ("Ask Dock…", with a
microphone button); right-click (or Control-click) for the menu: open Dock,
add your phone, start at login, quit.

Windows: a tray icon (Shell_NotifyIcon, e.g. via pystray) (docs/WINDOWS-PORT.md).
"""

import os
import signal
import subprocess
from pathlib import Path

from AppKit import (
    NSApp,
    NSBezierPath,
    NSEventMaskLeftMouseUp,
    NSEventMaskRightMouseUp,
    NSEventModifierFlagControl,
    NSColor,
    NSImage,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSScreen,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from dock_agent import bubble, hotkey

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "OneDock.app"
LOGIN_ITEM = Path.home() / "Library/LaunchAgents/com.onedock.dock.plist"

_item = None
_menu = None
_status = None
_login = None


def _face(listening: bool) -> NSImage:
    """Two eyes and a smile, drawn as a menu bar icon."""
    def draw(rect):
        (NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0.79, 1, 1) if listening else NSColor.blackColor()).set()
        for x in (5, 12):
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, 7, 4, 7), 2, 2).fill()
        smile = NSBezierPath.bezierPath()
        smile.setLineWidth_(1.8)
        smile.setLineCapStyle_(1)
        smile.moveToPoint_((3.5, 4.5))
        smile.curveToPoint_controlPoint1_controlPoint2_((17, 4), (7, 0.5), (13, 0.5))
        smile.stroke()
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_(NSMakeSize(21, 16), False, draw)
    image.setTemplate_(not listening)  # black/white with the menu bar, cyan while listening
    return image


class Actions(NSObject):
    def clicked_(self, sender):
        event = NSApp.currentEvent()
        if event.type() == 4 or event.modifierFlags() & NSEventModifierFlagControl:  # right-click / Control-click
            _item.setMenu_(_menu)  # (shown only for this click, so a normal click opens the chat box)
            _item.button().performClick_(None)
            _item.setMenu_(None)
        else:
            from dock_agent import talk  # (talk uses this module too)
            if talk.listening():  # clicked again: cancel
                talk.cancel()
            else:  # (be quiet if Dock is talking; otherwise open the chat box and listen)
                talk.tap()

    def openDock_(self, sender):
        bubble.show_welcome()

    def addPhone_(self, sender):
        bubble.show_welcome("phone")

    def toggleLogin_(self, sender):
        set_start_at_login(not LOGIN_ITEM.exists())
        sender.setState_(1 if LOGIN_ITEM.exists() else 0)

    def quit_(self, sender):
        os.killpg(os.getpgrp(), signal.SIGTERM)  # the server, this agent and the tunnel


_actions = Actions.alloc().init()


def start() -> None:
    """Main thread."""
    global _item, _menu, _status, _login
    _item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    button = _item.button()
    button.setImage_(_face(False))
    button.setToolTip_(f"Click to ask Dock, or press {hotkey.KEY_NAME}. Right-click for more.")
    button.setTarget_(_actions)
    button.setAction_("clicked:")
    button.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)
    menu = _menu = NSMenu.alloc().init()
    _status = menu.addItemWithTitle_action_keyEquivalent_("Dock is starting…", None, "")
    menu.addItemWithTitle_action_keyEquivalent_(f"Click the face or press {hotkey.KEY_NAME}, then talk or type", None, "")
    menu.addItem_(NSMenuItem.separatorItem())
    for title, action in (("Open Dock…", "openDock:"), ("Add your phone…", "addPhone:")):
        menu.addItemWithTitle_action_keyEquivalent_(title, action, "").setTarget_(_actions)
    menu.addItem_(NSMenuItem.separatorItem())
    _login = menu.addItemWithTitle_action_keyEquivalent_("Start Dock when I log in", "toggleLogin:", "")
    _login.setTarget_(_actions)
    _login.setState_(1 if LOGIN_ITEM.exists() else 0)
    menu.addItemWithTitle_action_keyEquivalent_("Quit Dock", "quit:", "q").setTarget_(_actions)
    AppHelper.callLater(2, lambda: print("Menu bar face at x=%.0f y=%.0f" % where()))


def where() -> tuple[float, float]:
    """The face's middle, in screen points from the top-left (for tests)."""
    frame = _item.button().window().frame()
    screen_height = NSScreen.screens()[0].frame().size.height
    return frame.origin.x + frame.size.width / 2, screen_height - frame.origin.y - frame.size.height / 2


def set_listening(on: bool) -> None:
    _item.button().setImage_(_face(on))


def set_focus(text: str) -> None:
    """The focus countdown next to the face ("" when no session)."""
    _item.button().setTitle_(f" {text}" if text else "")


def set_status(text: str) -> None:
    _status.setTitle_(text)


def apply_start_at_login(on: bool) -> None:
    """From the settings page: switch it, and update the menu's tick. Main thread."""
    set_start_at_login(on)
    if _login is not None:
        _login.setState_(1 if LOGIN_ITEM.exists() else 0)


def set_start_at_login(on: bool) -> None:
    """Start OneDock.app at login (a LaunchAgent that opens the app)."""
    if not on:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/com.onedock.dock"], capture_output=True)
        LOGIN_ITEM.unlink(missing_ok=True)
        return
    LOGIN_ITEM.parent.mkdir(parents=True, exist_ok=True)
    LOGIN_ITEM.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.onedock.dock</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>{APP}</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
""")
