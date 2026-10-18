"""Dock's desktop agent for Windows.

The same jobs as the Mac agent (dock_agent/actions.py), with the same names
and the same answers, so the server and the phone page don't need to know
which computer they're talking to. Mac-only parts are swapped for Windows
ones (docs/WINDOWS-PORT.md):

- UI Automation instead of the Mac's Accessibility API (menus, buttons, text),
- Windows Search instead of Spotlight,
- a tray icon instead of the menu bar face, a WebView2 window for the bubble,
- a low-level keyboard hook for the talk key (press Alt+Space),
- Windows' own voice (SAPI) for spoken replies.

The parts that already work on both (finding files, Downloads, speech to
text, the server connection) are shared with the Mac agent.
"""
