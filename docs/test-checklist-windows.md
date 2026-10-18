# Dock test checklist (Windows)

This only checks that the Windows pieces work: install, start, the connection, the microphone, the voice, acting on the PC and drawing on screen. The features themselves are the same code as on the Mac and are tested there ([test-checklist.md](test-checklist.md)).

If a check fails, copy the lines around it from the log (`%LOCALAPPDATA%\OneDock\dock.log`, or run `scripts\start.ps1` in PowerShell to watch it live) and send them to me.

**Before you start:** copy the OneDock folder to the PC, and copy `server/google_oauth_client.json` too if you want Google. Install the AWS CLI (`winget install Amazon.AWSCLI`) and run `aws login` (region `us-east-1`).

## 1. Install and start
- [ ] `powershell -ExecutionPolicy Bypass -File scripts\install.ps1` finishes without red errors, and **OneDock** is in the Start menu.
- [ ] Open OneDock → the welcome window opens, and a small face appears in the tray by the clock.
- [ ] The welcome window's steps turn green: Microphone, AI. (No Accessibility step on Windows.)
- [ ] The log shows `Desktop agent connected`, `Bubble page ready` and `Talk key ready: press Alt+Space`.

## 2. Talk and hear
- [ ] Press **Alt+Space** once → the chat box opens at the bottom right and says "Listening". Alt+Space types nothing into your app, and the app's menu bar doesn't light up.
- [ ] Say "open my downloads" and stop → File Explorer opens Downloads, a ✓ card shows, a short sound plays. (This checks the microphone, speech to text, the AI and the server in one go.)
- [ ] Type "how was my week?" in the box → Windows' voice says the answer.
- [ ] Click the tray face → the same box opens. Esc closes it, and your app has the keyboard again.

## 3. Act on the PC
- [ ] "Open Notepad" → it opens.
- [ ] "Put Notepad on the left and File Explorer on the right" → both windows move.
- [ ] In Notepad: "where's save as?" → an arrow points at the menu item on screen; "do it" opens Save As.
- [ ] In Notepad, type "i has a apple", select it, say "fix the grammar" → a suggestion card; **Replace** fixes the text (Ctrl+Z undoes it).
- [ ] "Remember this workspace as Test", close the windows, "open my Test workspace" → they come back.

## 4. Phone and quit
- [ ] Tray › **Add your phone…** → scan the QR code → the phone shows "Connected", and a card shows on both.
- [ ] Tray › **Quit Dock** → the tray face goes away, and no `python.exe` is left in Task Manager.
- [ ] Start OneDock again → it starts normally (the token and settings are kept).
