# Dock test checklist (Mac)

One line per check. Tick it when it works. If one fails, note what you said and roughly when, so it can be matched in the log (`~/Library/Logs/Dock/dock.log`).

📱 = needs the phone. On Windows, use [test-checklist-windows.md](test-checklist-windows.md).

**Before you start:** open **OneDock.app**. The welcome window's steps are green (Accessibility, Microphone, AI). Have VS Code, RStudio, Safari and TextEdit open.

## 1. Start and talk
- [ ] Press **⌥ Space** once and say "open my downloads" → the chat box opens, "Listening", then Finder opens Downloads with a ✓ and a short sound.
- [ ] Press ⌥ Space and type instead → the listening stops. **Esc** closes the box. Clicking the menu-bar face does the same as ⌥ Space.
- [ ] Ask "how was my week?" → the Mac says the answer. Press ⌥ Space while it talks → it stops.
- [ ] Say something vague ("do the thing") → Dock asks a short question back.
- [ ] Menu-bar face › **Quit Dock** → nothing is left running (`pgrep -f dock_` prints nothing).

## 2. Computer control
- [ ] "Open my stat310 folder" → the right folder opens.
- [ ] "Open the stat525 file I worked on yesterday" → the file really opens.
- [ ] "Open VS Code" works. "Open Photoshop" (not installed) → says it isn't there and opens nothing.
- [ ] "Put Chrome on the left and VS Code on the right" → split. "Close all windows except VS Code" → the others hide.
- [ ] "Remember this workspace as Test" (with a Finder window too), quit the apps, "open my Test workspace" → everything comes back.

## 3. App help (the demo)
- [ ] iMovie: "where's the split tool?" → spoken answer (Modify › Split Clip, ⌘B) and an arrow on the menu item. "Do it" → the clip splits.
- [ ] VS Code: "how do I split the screen?" → arrow on Split Right. "Split the screen" → it just does it.
- [ ] Safari on the AWS console: "how do I check my costs?" → the arrow on "Billing and Cost Management".
- [ ] Something not in any menu ("how do I translate this page?" in Chrome) → a **Search Google?** card; nothing opens until you tap Search.
- [ ] "Where's quit?" then "do it" → Dock refuses to click Quit.

## 4. Writing and reading
- [ ] Select messy text in TextEdit, say "check this text" → a suggestion card; your text hasn't changed. **Replace** fixes it (⌘Z undoes it); **Insert below** keeps the original.
- [ ] Select code in VS Code, say "read this to me" → it reads the selection.
- [ ] Open a PDF, say "summarize this" → a short summary.

## 5. Downloads and saving
- [ ] Put a homework PDF named "document.pdf" in Downloads, say "help me tidy my downloads" → it suggests the right class folder; unsure files stay; nothing moves until you agree; "undo" puts files back.
- [ ] File › Save in TextEdit, say "where should this go?" → a folder suggestion; **Save here** saves there.

## 6. Calendar, notes and email
- [ ] Welcome window › **Sign in with Google** → the step turns green.
- [ ] "Remind me to call Mom at 5" → a ✓, and it's on your Google Calendar.
- [ ] "What's on today?" → matches your calendar.
- [ ] "What did I miss?" → the important emails first, the rest only counted.
- [ ] "Clean up my inbox" → a checklist; nothing moves until you say yes.

## 7. Focus mode
- [ ] "Focus on homework for 25 minutes" → the countdown shows by the menu-bar face (and on the phone).
- [ ] 📱 Walk away for 20 s → the timer pauses; come back → it resumes.

## 8. Phone 📱
- [ ] Scan the QR code in the welcome window → the phone shows "Connected", and every card shows on both the phone and the Mac.
- [ ] Tap the phone's face and say "open my downloads" → it works the same as on the Mac.
- [ ] Restart Dock → the phone reconnects by itself.

## 9. MCP server (for the video)
- [ ] MCP Inspector (`npx @modelcontextprotocol/inspector`, Streamable HTTP) on the phone address + `/mcp` with `Authorization: Bearer <.dock-token>` → it connects (protocol 2025-11-25) and lists 28 tools. Without the token → refused.

---

**When you're done:** tell me which boxes failed, with what you said and what happened, and I'll fix them.
