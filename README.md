# Dock

Alexa+ for your desk: ask out loud and it controls your computer and helps you inside the app you're using. **It works on a Mac (or a Windows PC) alone**: press ⌥ Space once (Alt+Space on Windows) and talk, like tapping the face on the phone. A docked phone is an optional extra screen and face. An optional focus mode adds a timer (and desk presence with the phone's camera).

## How you use it

**The first time (about 2 minutes)**
1. Run the installer (below), or double-click **OneDock.app** in this folder. A small face appears in the menu bar, and a welcome window opens.
2. The welcome window has four steps that turn green by themselves: let Dock see menus (Accessibility), let Dock hear you (Microphone), connect the AI (your AWS login), and try it: press **⌥ Space**, say "open my downloads".
3. Close the window. That's it. Optional: "Add your phone" (a QR code) and "Start Dock when I log in".

**Every day**
- Nothing to open: Dock starts with the Mac (if you turned that on) and waits in the menu bar.
- **Click the face** in the menu bar for a chat box: type, tap a suggestion, or click its microphone and talk (it sends when you stop). Its **gear** opens Dock's settings and setup (start at login, folder suggestions, calendar, phone). Right-click the face for the menu.
- Or press **⌥ Space** anywhere (or click Dock's face in the menu bar) and say what you want; Dock sends it when you stop talking, or type instead. A small bubble under the menu bar shows the answer, the Mac says it, and an arrow points on screen when it helps. Questions like "Save it in stat310?" appear in the same bubble with buttons.
- Focus: say "focus on homework for 25 minutes"; the countdown shows next to the face in the menu bar.
- With a phone docked, the cards and the face show on the phone instead, and you can talk to the phone too.

**When you're done**
- Just leave it. Dock stays in the menu bar like Dropbox or the clock: it does nothing until you hold the key, and the microphone is only on while you hold it. Closing the lid is fine; it reconnects when you open it.
- To stop it: the face in the menu bar › **Quit Dock**. To stop it starting at login: untick **Start Dock when I log in** there.

## Pieces
- `server/`: the Dock MCP server (Streamable HTTP, MCP spec 2025-11-25). It also serves the phone web app and keeps WebSockets to the laptop and phone.
- `server/static/`: the phone web app (plain HTML/JS, no build step).
- `agent/`: the desktop agent (Python) that does the actual work on the computer. It is also the menu-bar app: the talk key, speech to text (Whisper, on the computer), spoken replies and the bubble. `agent/dock_agent/win/` is the Windows version (tray icon, UI Automation): [docs/WINDOWS-PORT.md](docs/WINDOWS-PORT.md).
- `app/` + `scripts/build_app.sh`: **OneDock.app**, the small app that starts Dock (so macOS asks permissions for "OneDock").

## Install (Mac)
```bash
git clone <this repo> && cd OneDock && ./scripts/install.sh
```
The installer adds what's missing (uv, cloudflared), installs Dock, creates your private token, builds **OneDock.app**, can start Dock at every login, and opens it. The welcome window walks you through the rest (see "How you use it"). The first start downloads the speech model (Whisper small.en, about 480 MB, once).

You need an AWS account with Amazon Bedrock access (`aws login`, region `us-east-1`).

## Install (Windows 10 or 11)
```powershell
git clone <this repo>; cd OneDock; powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```
The same steps as on the Mac (uv and cloudflared come from winget), then **OneDock** is in the Start menu and Dock lives in the tray by the clock. Press **Alt+Space** to talk. Details and differences: [docs/WINDOWS-PORT.md](docs/WINDOWS-PORT.md); test list: [docs/test-checklist-windows.md](docs/test-checklist-windows.md). *(Written and checked on the Mac; not yet run on a Windows PC.)*

- Open Dock: double-click **OneDock.app** (opening it again just shows the welcome window). Quit: menu-bar face › Quit Dock. Logs: `~/Library/Logs/Dock/dock.log`. For development you can still run `./scripts/start.sh` in Terminal (Ctrl+C stops). Stop starting at login: `./scripts/uninstall.sh`.
- **Install the phone app once; its link never changes.** The free Cloudflare tunnel gets a new address on every restart, so Dock also puts the phone app's files in a small S3 bucket in your AWS account (`https://dock-app-….s3.us-east-1.amazonaws.com/index.html`, made on the first run and kept in `server/.data/webapp.json`). Next to them, `address.json` holds the Mac's current tunnel address, and the installed app reads it each time it connects, so it finds the Mac by itself. Only the app's own files and that address are public. The pairing token never leaves your devices: the QR code passes it after `#`, and the phone remembers it. On the phone, open the QR link in Chrome, then ⋮ › **Add to Home screen**. Set `DOCK_WEBAPP=off` to skip S3 (then the link changes on each restart), or `DOCK_PUBLIC_URL` if you host the server yourself. To remove the bucket: `aws s3 rb s3://<bucket> --force`.
- MCP endpoint: `http://localhost:8000/mcp` with `Authorization: Bearer <token from .dock-token>`. Try it with `npx @modelcontextprotocol/inspector` (transport "Streamable HTTP").
- Models: Claude Haiku 4.5 understands each request and picks the tool (`DOCK_ROUTER_MODEL`, with prompt caching), Amazon Nova 2 Lite does small jobs like summaries (`DOCK_MODEL`), and Claude Haiku 4.5 does tidy-up plans (`DOCK_SMART_MODEL`).

## How the simulated Alexa+ works
Press ⌥ Space on the Mac (Whisper turns speech into text on the Mac), or tap the microphone on the phone (Chrome's speech recognition) -> `POST /api/voice` -> Bedrock picks a Dock tool -> the server calls it through its own MCP endpoint over Streamable HTTP, like Alexa+ would -> the desktop agent does the work -> the reply is spoken (by the Mac, or by the phone).

## Tools
| Tool | What it does |
|---|---|
| `open_folder(name)` | Opens a standard folder, or finds any folder by name (Spotlight, including iCloud and cloud drives) |
| `find_files(name, kind, folder, days)` | Finds files by name or folder words, type, folder and date |
| `open_file(path, show_in_finder)` | Opens a found file, or shows it in Finder (never opens anything that could run a program) |
| `open_app(name)` | Opens an app by a spoken name ("VS Code", "Chrome") |
| `arrange_windows(layout, screen, hide_others)` | "Chrome on the left, Notes on the right", "make this full screen", "move this to my other screen" |
| `notes(action, text)` | Quick notes and to-dos ("note: ask the professor about Q3", "what's on my list?") that come back at the right session |
| `get_schedule(day)` / `get_ready(for_what)` | Google Calendar (one **Sign in with Google** button, which also connects Gmail; see [docs/GOOGLE-CALENDAR.md](docs/GOOGLE-CALENDAR.md)): "what's next?"; "get ready for stat class" opens the meeting link, the class folder and related notes |
| `workspace(action, name)` | Save, open or list workspaces: the apps, documents, tabs and window positions on screen |
| `suggest_folders(all_downloads)` / `put_in_folder(moves, folder)` / `undo_last_action()` / `set_folder_suggestions(on)` | "Where should this go?" for one file or the whole Downloads folder (with questions); put files there after you agree (or finish the open Save window); undo; automatic suggestions on or off (off by default) |
| `read(how, path)` | Summarize, or read out loud, the selected text, the open document, or a file |
| `get_recap(period)` | Today or yesterday: time per app, files worked on, questions asked. Week: focus sessions and how much time Dock saved you |
| `start_focus_session(goal, minutes, workspace)` / `control_focus(action)` / `focus_status()` | Focus mode: guards your goal, not just your time. Timer, camera presence, gentle drift nudges, welcome-back, break flashcards, proof-of-work report |
| `app_help(question, do_it)` | Finds a menu item in the app in front, says where it is and its shortcut, points at it on screen, and shows it on the phone. Not in the menus: the window's own labelled buttons (toolbar icons), then a look at a screenshot of just that window. `do_it` also clicks it |
| `do_app_action()` | "Do it": clicks the menu item Dock just pointed to (risky items like Delete or Quit are refused) |

**The phone screen** is Dock's face (Alexa colours, with an Amazon-style smile) and one short line, such as how much time Dock saved you this week. When Dock answers or suggests something, the face steps aside and the card shows big in the middle; when it's done, the face comes back. A cyan light bar at the bottom shows when Dock is listening, thinking or talking. Tap the phone's face and it acts as the trigger: the chat box opens **on the Mac** (type with the Mac keyboard) while the phone listens. Type on the Mac and the phone stops listening; talk and the Mac's box closes. With no Mac connected, the phone's own typing box opens instead. A few things to ask sit under the face (on both sides of it when the phone is on its side, so the face stays big). The screen stays on and dims itself after 45 s of quiet; the first tap only wakes it. Focus mode is a small **Focus** button at the top left: during a session the screen shows a countdown ring, and the face returns only when it matters (you stepped away, drifted, or came back). The **Shortcuts** view has buttons for the app in front on the Mac, which change when you switch apps, with Dock's answers, cards and **"Try saying…"** examples above them. If you turn on **folder suggestions** (a switch on the phone, off by default), when a **new download** finishes the phone suggests where to put it (*"Put it in Documents/school/stat310?"* Move / Other… / Not now). When a **Save window** opens in any app, Dock suggests the folder on the phone and next to the window, and **Save here** saves it there. Both learn from where you put files before. With the switch off, a Save window makes the phone ask first (*"Want Dock to suggest a folder?"* Yes / No); the question disappears if you close the Save window, pick a folder yourself, switch apps or ask Dock something else. You can also ask "where should this go?" for one file.

See [MCP-SERVER.md](MCP-SERVER.md) for the MCP server at a glance (what makes it different, all 28 tools, how to try it), [CAPABILITIES.md](CAPABILITIES.md) for everything Dock can do with tested examples, and [docs/test-checklist.md](docs/test-checklist.md) (Mac) or [docs/test-checklist-windows.md](docs/test-checklist-windows.md) (Windows) for the hands-on test lists.

## License
MIT
