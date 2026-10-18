# Dock on Windows

Every Dock feature has a Windows version. The server and the phone/bubble page are the same on both computers. The desktop agent has a Windows version in `agent/dock_agent/win/`: it does the same jobs, with the same names and answers, so the server doesn't need to know which computer it's talking to. When it connects, the agent tells the server it's on Windows, so Dock says "Ctrl+Z" instead of "Command Z", shows **Alt+Space** as the talk key, and calls the computer "PC".

**Status (Oct 17, final check before the first Windows run):** written on the Mac and checked there as far as a Mac can: every file passes pyflakes (no unknown names or missing imports), the Windows agent has the same 47 actions with the same arguments as the Mac's, the lockfile has Windows builds of every package (Python is pinned to 3.12 in `.python-version`, as on the Mac), and every Windows library call was checked against that library's own code. Today's Mac fixes (tap-to-talk, "close everything except…", Photoshop never opening a "photos" folder, reading your selection, tidy reading file contents, File Explorer in workspaces) are in the Windows version too. It hasn't run on Windows yet, so expect a few fixes on the first real run. Use [test-checklist-windows.md](test-checklist-windows.md).

## Install and start (Windows 10 or 11)
1. Install Git, then clone the repo.
2. In PowerShell, from the repo folder: `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`. It installs `uv` and `cloudflared` (with winget), Dock's Python packages, makes your token, checks the AWS login, and adds **OneDock** to the Start menu and the desktop (and, if you say yes, to start at login).
3. AWS: `winget install Amazon.AWSCLI`, then `aws login` (region `us-east-1`).
3b. Google (optional, for Calendar and Gmail): copy `server/google_oauth_client.json` from the Mac to the same place on the PC. It's kept out of git on purpose (it holds a secret), so the clone doesn't have it. Without it, the Google step just stays off.
4. Open **OneDock** from the Start menu. The welcome window opens; Dock then lives in the **tray by the clock** (a small face).
- To see what's happening: `scripts\start.ps1` in PowerShell shows the log live. When started from the Start menu, the log is in `%LOCALAPPDATA%\OneDock\dock.log`.
- To remove the shortcuts: `scripts\uninstall.ps1`.

## What each Mac piece became
| Agent part (Mac → Windows) | What it does | Mac uses | Windows uses |
|---|---|---|---|
| `menus.py` → `win/menus.py` | Read the app's menus and shortcuts, press items | Accessibility API | Classic menus: the Win32 menu API (whole menu without opening it; WM_COMMAND to press). Newer menus (new Notepad, File Explorer, VS Code, Office): UI Automation, opening each menu for a moment, only when you ask |
| `onscreen.py` → `win/onscreen.py` | Buttons not in menus; screenshot + click | Accessibility, `screencapture` | UI Automation (all parts read in one call), Pillow `ImageGrab`, `SetCursorPos` |
| `overlay.py` → `win/overlay.py` | The arrow and highlight; hides on any input | Click-through NSWindow | Click-through layered window (a see-through colour), drawn with Pillow |
| `reading.py` → `win/reading.py` | Selected text, replace it, insert below, window text, file text | Accessibility, ⌘C/⌘V | UI Automation text, Ctrl+C/Ctrl+V with the clipboard put back; PDFs with pypdf, Word files read directly |
| `savepanel.py` → `win/savepanel.py` | Notice Save windows, switch the folder, Save | AX "save-panel" | The standard Save As dialog (#32770): type the folder into "File name" + Enter, put the name back, Save |
| `apps.py` → `win/apps.py` | Open apps by spoken name | `/Applications` | The Start menu's list (`Get-StartApps`), opened through `shell:AppsFolder` |
| `arrange.py` → `win/arrange.py` | Windows left/right/thirds/full, other screen | Accessibility | `SetWindowPos` on the screen's usable area (without the taskbar); "full" maximizes |
| `workspaces.py` → `win/workspaces.py` | Save/reopen apps, files, folders, tabs, positions | AppleScript, Accessibility | Window list, File Explorer folders (Shell.Application), each browser window's current page (its address bar), files from the window title + Recent files |
| `watch.py`, `recap.py` → `win/watch.py`, `win/recap.py` | Front app, time per app, files changed/opened | NSWorkspace, Spotlight | Polling the front window, `GetLastInputInfo`; files changed by walking your folders, files opened from Windows' Recent folder |
| `hotkey.py` → `win/hotkey.py` | Press once to talk or type (swallowed, so it doesn't type) | ⌥ Space, Quartz event tap | **Alt+Space**, low-level keyboard hook (Alt is "masked" so the menu bar doesn't light up) |
| `voice_out.py` → `win/voice_out.py` | Spoken replies, "done" sound | `say`, NSSound | SAPI (Windows' voice), `winsound` |
| `bubble.py` → `win/bubble.py` | Cards window, chat box, welcome window | NSPanel + WKWebView | pywebview (WebView2), see-through, always on top, never takes the keyboard except for the chat box. Bottom right, above the taskbar |
| `menubar.py` → `win/tray.py` | Face icon, countdown, menu, start at login, quit | NSStatusItem | pystray tray icon; start at login = a shortcut in the Startup folder |
| shared: `files.py`, `tidy.py`, `speech.py`, `link.py`, `workspaces_common.py` | Find files, Downloads, speech to text, the server connection | Spotlight, `mdls` | Windows Search (the same index the Start menu uses), the file's "Zone.Identifier" (which site a download came from) |

## Differences worth knowing
- **No permissions to grant** for menus, buttons or screenshots on Windows. The setup page hides those steps. The microphone only needs Windows' "Let desktop apps access your microphone" switch.
- **Apps without a menu bar** (Chrome, Edge, most Store apps) are helped through their buttons, like toolbar buttons on the Mac. Office's ribbon buttons are found the same way (the tab that's open).
- **Pointing at an item in a newer menu** opens that menu, like on the Mac. Reading those menus opens each one for a moment the first time you ask in an app (then they're remembered for 5 minutes). Switching apps never opens anything: the phone's shortcut pad only gets apps with classic menus.
- **Writing fixes** always paste (Ctrl+V), with your clipboard put back, because Windows can only replace a whole text box, not the selection.
- **Workspaces** remember each browser window's current page, not every tab. Store apps (Calculator, Settings) aren't reopened.

## Testing on the PC
Use [test-checklist-windows.md](test-checklist-windows.md): a short check that install, start, the talk key, the microphone, the voice, acting on the PC and the phone link work. The features themselves are the same code as on the Mac and are tested there.
