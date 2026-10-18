# What Dock Can Do

*Updated Oct 17, 2026.* ✅ = works today on Andy's Mac with the phone web app. *Tested* = run end to end on the current models (Claude Haiku 4.5 picks the tool; Nova 2 Lite does small jobs). 💲 = uses AI (about $0.001). **Free** = no AI.

You talk to Dock by **tapping to talk** or **typing** on the docked phone (or, once Amazon grants access, through Alexa+ on the Echo Pop). Dock remembers the last few exchanges, so follow-ups like "do it" or "open the newest one" work.

---

## At a glance

| # | Capability | Example | Cost | Others with something similar | Dock's edge |
|---|---|---|---|---|---|
| 1 | Open any folder | "Open my stat310 folder" | Free | Spotlight, Raycast, Alfred (typed); Siri | By voice from across the room; finds folders deep in iCloud/OneDrive |
| 2 | Find files | "What PDFs do I have in stat 310?" | Free | Spotlight, Raycast, Alfred; Siri on Mac | Understands folder words and loose dates ("yesterday"), then can open or summarize the result |
| 3 | Open files / show in Finder | "Open the stat310 homework I worked on yesterday" | Free | Spotlight, Raycast, Siri | Finds and opens in one sentence |
| 4 | Open apps | "Open VS Code" | Free | Siri, Spotlight, Raycast, macOS Voice Control | Same as others, just part of one assistant |
| 5 | **App help: "where is…?"** | "How do I cut this clip in two?" → Split Clip ⌘B | Free / 💲 | macOS Help-menu search (exact words only); Copilot Vision Highlights (Windows, share a window first); Gemini/ChatGPT screen sharing | **Reads the app's real menus**: exact name and shortcut, loose wording, spoken + arrow on screen + card on phone, no sharing step, any Mac app |
| 6 | **"Do it"** | "Do it" → clicks Split Clip | Free | macOS Voice Control (you must know the label); computer-use agents (slow) | One word right after the answer; safe list of what it will click |
| 7 | Multi-step tasks | "Summarize my stat310 homework 3" → find, then summarize | 💲 | ChatGPT agent, Claude computer use, Perplexity, Simular (general but slow); Siri Shortcuts (pre-built) | 2–5 s instead of minutes; only safe actions |
| 8 | **Phone shortcut pad** | Phone shows Split ⌘B, Undo, Import… for iMovie | Free | Stream Deck + its phone app (manual setup); MacBook Touch Bar (discontinued) | **Builds itself per app** from real menus; free on the phone you own |
| 9 | Saved workspaces | "Remember this workspace as Study" | Free | Moom, Workspaces (Mac apps); PowerToys Workspaces (Windows); browser tab groups | By voice; saves apps + documents + tabs + folders + window spots in one go |
| 10 | Tidy Downloads | "Help me tidy my downloads" | 💲 | Hazel (you write rules); AI folder organizers like Sparkle | **Reads what each file says**, uses where it came from and your past moves, **leaves unsure files alone**, moves only after you agree, undo |
| 11 | Read / summarize | "Summarize this" / "read this to me" | 💲 / Free | Apple Intelligence Writing Tools, macOS Spoken Content, ChatGPT/Claude apps | By voice for any file it can find; reads aloud on the phone speaker |
| 12 | End-of-day recap | "What did I work on today?" | 💲 | Screen Time, Timing, RescueTime | One spoken summary of apps + files + what you asked Dock; data stays on your Mac |
| 13 | **Focus mode that guards your goal** | "Focus on stat310 homework for 50 minutes" (or until you stop) | Free (💲 tiny drift check) | Forest, Freedom, Opal, Apple Focus (timers and blockers) | Knows *what you're working on*: opens the matching workspace, pauses when the phone camera sees you leave, says **"welcome back, you were in hw_03.Rmd"** and reopens it, nudges gently when you drift (and **knows a dplyr tutorial on YouTube is on-task**), quizzes you on your own shortcuts during breaks, and ends with proof of work: files changed, time on task |

---

## How Dock stands out

**One line:** Dock is the only assistant you can ask out loud, from across the room, *how to do something in whatever Mac app you're using*. It answers with the exact menu item and shortcut, points at it on screen, clicks it if you say "do it", and turns your phone into a shortcut pad for that app.

**What nobody else combines**
1. **Help inside any app, by voice.** No window sharing, no chat box, no exact words needed.
2. **Exact, not guessed.** Answers come from the app's own menus, so names and shortcuts match your version.
3. **Shows *and* does.** Spoken answer + arrow on screen + card on the phone, then "do it".
4. **Your phone becomes the app's control pad.** Buttons for the app in front, built from its real menus, that change when you switch apps.
5. **Fast, safe, light.** About a second per answer, a fixed list of safe actions (no deleting, no shell), about $0.001 per request, under 200 MB of RAM and near-zero CPU when idle, open source.

**Be honest about the rest.** Opening apps, finding files and summarizing exist elsewhere (Spotlight, Siri, Apple Intelligence). In Dock they're there because one voice assistant should handle your whole desk. The headline is app help.

**What to show in the demo**
- "How do I cut this clip in two?" → arrow on Split Clip → "do it" → the clip splits. Use loose wording, not "split", to show it beats Help-menu search.
- Switch to RStudio and the phone pad changes by itself.
- Select a sloppy paragraph, say "fix the grammar", then tap Replace on the suggestion card.

### Dock vs the big assistants

| | What it does well | What it can't do that Dock does |
|---|---|---|
| **Siri** (Mac) | Opens apps, searches files, sets timers, all by voice | Can't tell you where a feature is inside a third-party app or click it. New AI features only work in apps that adopt Apple's App Intents. No writing fix you approve first |
| **Apple Intelligence** | Summarizes and rewrites selected text, built into macOS | No app help, no "do it", no phone pad. It works on text, not on the app's controls |
| **Microsoft Copilot** (Vision + Highlights) | Sees a shared window and highlights where to click | Windows only, you must share the window first, and it guesses from pixels instead of reading the real menu. No shortcut, no phone pad |
| **ChatGPT** (desktop app, agent) | Very capable chat; its agent can do long tasks on a virtual computer or browser | Lives in a chat window, isn't aware of your apps' menus, and agent tasks take minutes. Nothing on your desk listening |
| **Claude** (desktop, computer use) | Very capable chat; computer use can operate any app through screenshots | Screenshot-and-click loops are slow and costly, and it can misclick. Dock does menu actions directly in about 1 s. *(Claude Desktop could even use Dock's MCP server as a tool.)* |
| **Computer-use agents** (Simular, UI-TARS, Perplexity…) | General tasks in any app | Minutes per task, broad permissions, and they click screen positions, not menu items |

**In one sentence:** the others either *talk about* your apps (chat assistants) or *poke at* them through screenshots (agents). Dock reads and uses the apps' own menus, so it's exact, fast and safe, and it stays out of the way on your desk.

---

## Details

### 1–4. Folders, files and apps ✅ · Free
| Say *(tested)* | Result |
|---|---|
| "Open my downloads" | Opens Downloads (0.9 s) |
| "Open my stat310 folder" | Finds and opens `Documents/school/stat310` (2 s); "stat 310" or "STAT-310" also work |
| "What PDFs do I have in stat 310?" | *"9 PDFs… newest are Andy_hw3.pdf and hw_03.pdf, Monday 11:20 PM"* |
| "Open the stat310 homework I worked on yesterday" | Searches, then opens `hw_03.Rmd` in RStudio (2.5 s) |
| "Show the newest one in Finder" | Highlights it in Finder |
| "Open calculator" | Opens Calculator. Unknown apps (e.g. "Word" when not installed) get "I couldn't find…", never the wrong app |

Search covers your home folder, iCloud Drive and cloud drives. It understands types (pdf, image, video, document, spreadsheet, slides, any extension) and dates ("today", "this week"). If nothing matches "yesterday", it shows the newest matches.

### 5–6. App help and "do it" ✅
| App | Say *(tested unless noted)* | Answer |
|---|---|---|
| iMovie | "Where's the split tool?" | Modify → Split Clip **⌘B**, arrow on screen (0.8 s) |
| iMovie | "How do I cut this clip into two pieces?" | Same item without saying "split" 💲 |
| iMovie | "How do I export my movie?" | File → Share → File |
| RStudio | "How do I knit this?" / "run this chunk" / "where is the console?" | Knit Document **⇧⌘K** / Run Current Chunk **⇧⌘↩** / Move Focus to Console **⌃2** |
| VS Code, Chrome *(menu checked)* | "Open the terminal" / "where are my downloads?" | View → Terminal **⌃\`** / Window → Downloads **⇧⌘J** |

- Dock opens the menu and puts an orange box, an arrow and a label on the item, and shows a card on the phone. **The arrow goes away the moment you do anything** (click, type, scroll, or move the mouse more than a little), so it never stays while you're busy with something else. If you don't use the menu Dock opened, it closes by itself after 6 s *(tested)*.
- **Not in the menus? Dock checks the window itself** *(built Oct 16)*:
  1. **Labelled buttons (free, exact):** macOS lists most toolbar buttons with names even when they're not in a menu: Safari's Share and Downloads, Finder's view buttons, VS Code's "Toggle Panel (⌘J)" (shortcut included). It takes under 0.1 s in Safari and VS Code. Dock points at the real button, and "do it" presses it. *(Tested: VS Code "little green dot next to the folder name" → Source Control ⌃⇧G.)*
  2. **A look at the window** 💲 Claude Haiku, about $0.005: one screenshot of only the window in front, only when you ask. Haiku finds the rough spot, then a sharp close-up pins it down. Dock circles it, and "do it" clicks there. Needs Screen Recording (an optional step in the welcome window). *(Tested on VS Code: the Update button and the terminal panel's × were found exactly. A row of look-alike icons can still be one off, e.g. Extensions → Source Control, but those icons are labelled, so step 1 finds them first.)*
- **Web search** *(turned off for now; set `DOCK_WEB_SEARCH=on` to use it)*: Dock looks it up on the web (Bedrock's Nova web grounding, preferring the app's own help pages) and says the steps: Chrome *"translate this page"* → *"Click the Translate icon on the right side of the address bar…"* (from support.google.com, about 5 s); TextEdit *"count the words"* → Services › Word Count. About **$0.03 per search**, so only when the menus don't have it, or when you say "look it up online".
- **"Split screen" in VS Code** finds View › Editor Layout › Split Right (it used to pick Full Screen). Naming a feature always looks it up first; only "do it" / "click it" clicks the last thing Dock pointed to.
- **Commands just happen; questions get the arrow.** "Knit the document", "undo", "split the screen", "show the ruler" are done right away (risky items like Quit or Delete are still only pointed at). "How do I…?", "where's…?", "show me how…" point with the arrow and say the shortcut, so you can learn it. "Undo" is the app's Undo, unless Dock just moved files, then it puts them back *(tested in TextEdit; 51 of 51 routing phrases right)*. This works in **full-screen apps too** (tested in full-screen Safari: the hidden menu bar slides down and the arrow appears on top). Near the right edge of the screen, the arrow and label flip to the left of the item so the label isn't cut off *(tested)*. Not tried yet on a second monitor.
- It mentions greyed-out items instead of pretending ("select something first").
- **"Do it"** clicks that exact item, only in the same app, and never risky items (Delete, Quit, Erase, Log Out…). "Close this window" / "close the tab" closes it when you say "close" yourself (apps still ask about unsaved work); "do it" never closes anything.
- **Quiet when it just does it** *(built Oct 16)*: a command that worked shows a ✓ card (name and shortcut) on the phone and in the Mac bubble with a short sound, and Dock doesn't talk. Questions get one short spoken sentence ("Show Ruler is in Format, then Text. Or press Command R.") and one card: the card grows out of the phone's face when the answer is spoken, together with the arrow. Tap while Dock listens to cancel, or while it talks to stop it (also by clicking the menu-bar face).
- **Only points at what's really on screen** *(built Oct 16)*: buttons scrolled away or hidden off screen in web pages are skipped (a hidden "Add media" in Canva was pointed at before). A spot found by looking at a screenshot is only circled ("I think it's…"), never clicked by itself.
- Menus read in under 0.3 s in every app tried (Safari 891 items, RStudio 349, VS Code 292, iMovie 187).

### Time saved ✅ · Free *(tested)*
- The phone shows **"Dock saved you 12 min this week"** under the face (and in Settings). Ask *"how much time did Dock save me?"* (`get_recap`, week) for the breakdown, and the end-of-day recap mentions it.
- Rough, deliberately low estimates per thing Dock did: answering "where is…?" 20 s, a click for you (do it, pad button) 3 s, opening a folder/file/app 5 s, each app a workspace reopens 5 s, each tidied file 5 s.
- Only real actions count, kept per day in `.data/savings.json`, so they survive restarts.

### Suggestions worth asking ✅ · 💲 once per app *(tested)*
Under the face (and above the Shortcuts buttons) Dock shows a few things worth asking, never basics like "new tab" or "undo":
- **For the app in front:** once per app, Claude Haiku looks at the app's real menus and picks features that save time but are easy to forget, written the way you'd say them. Real results: Safari *"Translate this page to English"*, *"Read this page without clutter"*; VS Code *"Turn on zen mode"*, *"Jump back to last edit"*; Preview *"Add my signature to this"*; RStudio *"Knit this document to HTML"*; TextEdit *"Strip formatting from this text"*. Saved in `.data/app_suggestions.json` (about $0.005–0.015 once per app). Basic items are filtered out even if the AI picks one.
- **From what's going on (free):** a new download (*"Where should hw4.pdf go?"*), *"Summarize this"* in apps you read in, and *"What did I work on today?"* late in the day.

### 7. Multi-step ✅ · 💲
Up to 6 steps per request, and it recovers when a step fails. *Tested:* find → open; find → summarize (4.3 s); find, then "show the newest one in Finder" as a follow-up.

### 8. Phone shortcut pad ✅ · Free to use *(tested)*
- **Shortcuts** tab: up to 8 buttons for the app in front; it switches when you switch apps. A tap clicks the item on the Mac.
- iMovie: Split ⌘B, Join ⇧⌘B, Undo, Redo, Import ⌘I, Enhance, New Movie, Share › File. RStudio: Run Line ⌘↩, Run Chunk ⇧⌘↩, Knit ⇧⌘K, Insert Chunk ⌥⌘I, R Script, Save…
- AI picks the buttons once per app 💲, then remembers. Items you asked about come first, and risky items never appear.

### 9. Saved workspaces ✅ · Free *(tested)*
- "Remember this workspace as Study" (0.8 s) saves apps on the current desktop, their documents, Chrome/Safari tabs, Finder folders and window positions.
- "Open my Study workspace" (3.5 s) reopens everything and moves the windows back, without duplicating tabs. "What workspaces do I have?" lists them.

### 10. Tidy Downloads ✅ · 💲 Claude Haiku 4.5 *(tested)*
- "Help me tidy my downloads" (about 12 s) suggests a folder for each of your newest 40 downloads, using **what the file says** (the start of each PDF, Word file or text file: a "document.pdf" that starts with "STAT 310 Homework 03" goes to stat310), the name, the **website it came from**, where you put similar files before, and all your folders up to 3 levels deep (Documents, Desktop, iCloud, OneDrive). **It never forces a guess:** files it isn't sure about stay in Downloads, with at most one grouped question. It never suggests deleting anything.
- You agree by voice ("yes, move them"), by saying where ("put the screenshots in onebill-demo"), or by ticking items on the phone. "Undo" puts them back.
- On your Mac: resumes → `OneDrive/Documents/Resume`, HW2 → `CS589/HW2`, HW4 → `CS589`, and it asked about screenshots and 3D-print files.
- Only moves out of Downloads into your folders, never overwrites or deletes. *(Tested with a test file only; your real files weren't moved.)*
- **Suggestions read what the file says** *(built Oct 17)*: for a Save window, Dock reads the start of the document being saved (straight from the app's window, e.g. TextEdit's text); for a new download, the start of the file (PDF, Word, text). The AI sees about 800 characters, only when a suggestion is made. Tested: an "Untitled" TextEdit document starting *"STAT 525 Fall 2026 — Homework 4…"* got **not sure** from the name alone and **Documents/school/stat525** with its content.
- **Folder suggestions are off by default**, because each one is an AI call (about 3,500 tokens for the folder list, roughly $0.001). Turn them on with the switch in Settings (gear button), or say "turn on folder suggestions". The choice is kept in `server/.data/settings.json`. With it off, new downloads stay quiet, and a **Save window makes the phone ask first: "Want Dock to suggest a folder?" Yes / No.** Only Yes (tapped, or said out loud) calls the AI. No means no more questions for that Save window, even after a rename. The question goes away by itself when you close the Save window, pick a folder in it yourself, switch to another app, or ask Dock for something else. Turning the switch on while it's asking counts as Yes. You can still ask **"where should this go?"** for the open Save window or the newest download. *(Tested: off means no AI calls until Yes; Yes by tap (real tap in Chrome) and by voice; No, also after a rename; the question skipped on Cancel, on picking Documents by hand, on switching to Finder, and on asking "list my workspaces"; switch on suggests straight away with no question.)*
- **New downloads, right away** 💲 Nova 2 Lite: when a download finishes, about 5–7 s later the phone shows *"Put it in Documents/school/stat310/homework?"* with **Move**, **Other…** (starts "Put … in" in the keyboard box) and **Not now**. Saying "yes, move it" or "put it in Desktop instead" works too.
  - It learns your habits: every move is remembered (file name and folder only, in `server/.data/moves.json`) and given to the AI as examples. Moves you undo are forgotten, and the undone file isn't suggested again.
  - It stays quiet when it isn't fairly sure, and for installers (`.dmg`, `.pkg`). Files already in Downloads when Dock starts are left alone. Half-finished downloads (`.crdownload`) are ignored until they're done.
  - Suggestions wait on the phone until you answer, and are shown again after the phone reconnects.
- **While you choose where to save** 💲 Nova 2 Lite: when a Save window opens in any app (Chrome or Safari with "Ask where to save each file", or File › Save in TextEdit, Word…), about 1–2 s later the phone shows *"Saving STAT310 HW4.pdf — Save it in Documents/school/stat310/homework?"* with **Save here** and **Not now**. An orange arrow next to the window's **Where** menu says *"Dock suggests stat310 › homework"*.
  - **Save here** (or saying "save it there", or "save it on my Desktop") does what you'd do by hand: Command-Shift-G, types the folder, Return, then clicks Save.
  - Closing the Save window yourself clears the phone card. If you save it into Downloads anyway, Dock doesn't ask about the same file a second time.
  - The keys are typed through macOS System Events, because Safari's Save window runs in a separate system process that ignores plain key events.
  - *(Tested on your Mac with Safari and Chrome Save windows: STAT310 HW4 → `stat310/homework`, CS589 HW3 → `CS589`. Save here from the phone (including a real tap in Chrome), "save it on my Desktop instead" by voice in Safari and Chrome, and cancelling all worked. Test files were deleted afterwards.)*
  - *(Tested on your Mac with test files: STAT310 HW4 → `stat310/homework`, STAT310 Lab5 → `stat310/labs`, a CS589 file → `CS589`, a resume → `OneDrive/Documents/Resume`. Move, Not now, voice "yes, move it" and undo all worked, including real taps in Chrome at 360 px and 412 px. Test files were deleted afterwards.)*

### 11. Read / summarize ✅
- "Summarize this" uses the selected text, or else the open document (PDF, Word, RTF, text, R Markdown) 💲. "Summarize my stat310 homework 3" took 4.3 s.
- "Read this to me" reads it aloud on the phone, with a Stop button (free).
- If an app won't share the selection, Dock copies it with ⌘C and **restores your clipboard** *(tested)*.

### 12. Day recap ✅ · 💲 *(tested, 2 s)*
- "What did I work on today / yesterday?" gives a spoken recap plus a card with time per app (bars), files changed, and questions asked.
- App time is sampled every 30 s while you're active, and **stored only on your Mac** (`~/.dock/activity/`).

### 13. Focus mode ✅ *(tested end to end with a simulated phone; camera not yet tried on a real phone)*
| Say / do | What happens |
|---|---|
| "Focus on stat310 homework for 50 minutes", or the phone's **Focus** tab (goal + 15/25/50/90 min, any number, or **Until I stop**) | Starts the session. Opens a saved workspace whose name matches the goal. The phone shows the goal, a big timer and the face, and stays awake |
| Walk away *(phone camera; video stays on the phone)* | The timer pauses ("Away"). Back after 1+ minute: *"Welcome back! You were working in hw_03.Rmd"*, and that file comes back to the front *(tested)* |
| Drift to YouTube, Discord, Reddit… for 2 minutes | The face looks worried: *"Back to stat310 homework?"* No sound, nothing blocked *(tested)* |
| A dplyr or ggplot2 tutorial on YouTube | Counts as **on task**: a quick AI check uses what you've been working on (RStudio, hw_03.Rmd) *(tested; lofi music, MrBeast, Discord and Reddit were drift)* |
| "How's my session going?" / "pause" / "resume" | *"You've focused 20 minutes on stat310 homework, 30 minutes to go."* *(tested)* |
| Time's up, or "end my session" | Spoken summary plus the **proof-of-work** card: minutes focused, away and drifting, % on task, apps, files changed during the session. Asks *"Did you finish your goal?"* *(tested)* |
| "Take a break" | Break timer with **flashcards of the shortcuts you asked Dock about** (or the pad's shortcuts) *(tested)* |
| "How was my week?" | Hours per day (chart), sessions, goals finished, % on task, best day. Computed without AI *(tested)* |

Sessions are logged in `server/.data/focus_log.json`. Window titles are checked only during a session, and only distracting sites are sent to the AI for the relevance check.

---

## Setup ✅
- **One command:** `./scripts/install.sh` installs what's missing, creates the private token, optionally starts Dock at every login, and opens the setup page.
- **Setup page** (`localhost:8000/setup`, only on the Mac): live green checks for the desktop agent, Accessibility (one button opens the right settings), Amazon Bedrock, and a **QR code** to pair the phone. *(Tested: all checks green, and refused through the tunnel so the token can't leak.)*
- The server starts the secure phone address itself. `./scripts/start.sh` runs everything; `./scripts/uninstall.sh` stops the login start.

## Safety
- Fixed list of actions: open, search, read menus, point, click a menu item, workspaces, read text, move files out of Downloads (after you agree, with undo). **No shell commands, no deleting.**
- The AI must call a real tool every turn, so it can't claim it did something it didn't.
- Never opens things that could run a program (apps, scripts, installers); only touches your own folders.
- A secret token protects every connection (MCP, voice, laptop, phone). No screenshots, no camera yet.

## Mac alone: talk key, bubble, menu-bar app ✅ · Free *(built Oct 16)*
- **OneDock.app** starts Dock, so macOS asks for Accessibility and the microphone for "OneDock". It lives in the **menu bar** (a small face) with Open Dock, Add your phone, Start Dock when I log in, and Quit Dock. Opening it again only shows the welcome window. Quitting stops the server, agent and tunnel *(tested: nothing left running)*.
- **Click the face** for a chat box under it ("Ask Dock…", suggestions for the app in front, and a microphone button that sends by itself when you stop talking); right-click for the menu. The box takes the keyboard only while open, and Esc or clicking elsewhere gives it back *(tested: opens with the cursor in it; Esc closes it)*.
- **Press ⌥ Space once** anywhere (or click the face in the menu bar), like tapping the face on the phone: the chat box opens and Dock listens. It sends when you stop talking (or press ⌥ Space again); typing instead stops the listening, and Esc closes it. The key is swallowed, so it doesn't type into your app. The face turns cyan and the bubble says "Listening".
- **Light on memory:** the speech model is loaded the moment you press the talk key (it's ready before you finish talking) and freed after 10 minutes unused, so Dock idles at about 230 MB in total (agent 81 MB, server 84 MB, tunnel 21 MB, web views about 46 MB) and about 1% of one CPU core. Computers with 8 GB of RAM or less use the lighter `base.en` from the start *(measured on an M1 Pro)*.
- **Speech to text on the Mac** with Whisper (`small.en`, faster-whisper): free, offline, no Siri/Dictation setting needed, under 1 s per request on an M1 Mac; a computer that's too slow (over 2.5 s) switches to the lighter `base.en` (about 0.3 s) by itself. Short hints with your class folders (CS589, stat310…) help it spell names; the AI that picks the action also gets your folder names, so a mishearing like "start 310" still opens **stat310**, and folder search ignores spaces and accepts very close names *(tested)*. Compared on 56 clips in 7 English accents, whole chain (speech → right tool and name): small.en 47, base.en 45. Amazon Transcribe heard far less (17 of 48 on a harder set), and Voxtral on Bedrock sometimes invented names, so neither is used.
- **The bubble** shows the same cards as the phone (answers, shortcuts, "Put it in …?", "Save it in …?", focus report), and its buttons work without taking the focus from your app. The Mac speaks the answers. With a phone docked, the cards go to the phone instead.
- **Friendly AI-login error:** if `aws login` has expired, Dock says "My AI login has expired. On the Mac, open Terminal and run aws login" instead of "something went wrong" *(tested)*.
- Not yet tested with a real voice (only the Mac's own speaker into its mic, which isn't reliable). Windows: see [docs/WINDOWS-PORT.md](docs/WINDOWS-PORT.md).

## Email ✅ · 💲 Claude Haiku 4.5, about $0.005–0.01 per check *(built Oct 16; tested with a pretend mailbox, not yet a real one)*
- **Connect once** on the settings page: **Sign in with Google** connects Gmail and Google Calendar together (Google's sign-in page, once Dock is registered in Google Cloud, see [docs/GOOGLE-CALENDAR.md](docs/GOOGLE-CALENDAR.md); until Dock passes Google's review, users see "unverified app" once and at most 100 people can use it). No passwords or links to paste. It works the same on Windows, and the sign-in stays on this computer (`server/.data/`, readable only by you). *(Gmail sign-in tested with a pretend login, not yet a real Google account.)*
- **Sorting:** the AI sorts each email as **important** (a real person, deadlines, plan changes, bills or payments due, real security alerts, school, work), **update** (receipts, shipping, notifications, newsletters), **promotion** or **spam**. It only sees the sender, subject and the first 300 characters. Claude Haiku is used because the cheaper Nova 2 Lite kept filing a "payment due" bank email under updates (3 of 3 runs); Haiku got it right 3 of 3.
- **"What did I miss?"** says one short line per important email, urgent first, then counts the rest: *"Minh Tran: confirming the 4 pm meeting. Prof. Nancy Lee: HW4 deadline moved to tonight. Chase: credit card payment due October 18. Plus 3 updates, 2 promotions and 1 spam email."* The phone lists the important ones (urgent marked) with the same counts. About 3 s.
- **Morning briefing:** the first time you're at the computer each morning (5 am to noon), one card shows **Today** (your next events), **Email** ("12 new since last night") and **On your list** (open notes), with **Brief me** / Not now, once a day (a setting turns it off). Brief me, or saying "good morning" / "brief me" any time, reads it out: *"Good morning. Today: CS589 lecture at 10 AM, STAT 310 at 2 PM. Prof. Nancy Lee: HW4 deadline moved to tonight. Plus 2 promotions. On your list: email Nancy about the TA job. Want me to add submit STAT 525 HW4 by 11:59pm tonight to your list?"* Calendar or email not connected? They're just left out.
- **To-dos from email:** an important email that asks for something by a time gets a to-do with its deadline: **＋ Add "Submit STAT 525 HW4" to my calendar · due tonight at 11:59 PM** on the card, or "yes, add it" / "put it on my calendar". It goes on your list and, with the Google Calendar sign-in, on your calendar ending at the deadline, with a reminder an hour before (deadlines are offered first, soonest first).
- **Unsubscribe:** "unsubscribe from Old Navy", or the **Unsubscribe** button on a promotion in the clean-up list. Dock uses the sender's standard one-click unsubscribe when they offer it; otherwise their unsubscribe page opens on your Mac. Never for spam (it would tell spammers your address works), and never by sending an email *(tested with a pretend sender)*.
- **"Clean up my inbox" / "delete the spam" / "organize my email":** a checklist on the phone: spam and promotions → Trash, updates → folders like Receipts, Shipping, School (made if missing). **Nothing changes until you tap Clean up or say yes**, and you can untick any. Trash isn't emptied right away (Gmail keeps it 30 days). Otherwise Dock opens the mailbox read-only, so nothing is marked as read.
- **During focus, email waits.** Every 2 minutes Dock checks quietly. People on your **let-through list** get a card and a sound right away; so does email from a real person that the AI calls urgent (*"deadline tonight"*, *"family emergency"*; *"lunch sometime?"* waits). Ending the session says how many came in.
- **Alexa+ itself** only summarizes emails you forward to it (alexa@alexa.com); it doesn't read your inbox.

## Writing help, right where you type ✅ · 💲 Claude Haiku 4.5, about $0.002 per paragraph *(built Oct 17, tested)*
- **Select text in any app and say what you want:** "fix the grammar", "check this for typos", "make this more professional", "make it shorter", "make this friendlier", "translate this to Spanish". Dock **shows its suggestion first**, on the phone and the Mac, with what it changed marked (taken out in red, put in in green). Your text doesn't change until you choose:
  - **Replace** (or say "use it"): the suggestion goes in place of your selection, with no copying it into Gemini or Claude and back.
  - **Insert below** (or "put it below"): your original stays and the suggestion goes under it.
  - **Change more** (or just say "make it shorter too", "more formal"): the suggestion changes again, still nothing in your text.
  - **×** (or "never mind"): nothing changes.
  A fix changes only what's wrong (spelling, grammar, punctuation, capital letters) and keeps your formatting. After Replace or Insert below, **Command Z** undoes it, and a ✓ card says what changed ("Fixed 4 spots in TextEdit"), with no talking. If you've selected something else in the meantime, Dock asks you to select the original text again rather than change the wrong text.
- Works in native apps through Accessibility (tested in TextEdit: *"…ask weather… their was… becuase… dont…"* → *"…ask whether… there was… because… doesn't…"*, about 2 s) and in web pages by pasting, with your clipboard put back afterwards (tested in a Safari text box: *"the demo is gonna be late cuz the server broke again lol"* → *"I wanted to inform you that the demo will be delayed due to a server issue…"*).
- Dock checks (instantly, without copying anything) whether text is selected, so "make it shorter" means your text, not a window.

## Google when Dock isn't sure ✅ · Free *(built Oct 17, tested)*
- "Google how to cite a website in APA", "look up the UMass library hours": Dock **offers** the search first, on a *"Search Google?"* card (phone and Mac) with **Search** and **Not now**. Only Search (or saying "yes") opens it, in a **new tab of your default browser**.
- When app help can't find something in the app's menus or window, Dock offers a Google search for it ("RStudio how do I …") instead of a dead end, and anything no tool can do gets the same offer. *(Tested: "google how to cite…" showed the card and opened nothing; Not now closed it; "look up the UMass library hours" then "yes" opened one tab.)*

## Everyday desk basics ✅ · Free *(built Oct 16)*
- **Arrange windows:** "put Chrome on the left and Notes on the right", "make this full screen", "move this to my other screen", "just Chrome, hide the rest". Halves, thirds, quarters, full or centered, below the menu bar with small gaps; apps that aren't open are opened first. It never guesses: "Photoshop" (not installed) is refused instead of opening Photos *(tested with TextEdit and Calculator)*.
- **To-dos and reminders:** "note: ask the professor about Q3", "remind me to email Nancy", "what's on my list?", "cross off email Nancy". **With a time**, said any way: "remind me to call Mom at 5", "remind me in 20 minutes to take the laundry out", "remind me tomorrow morning to buy milk", "I need to submit the housing form by Friday noon", "add pay rent to my to-do list for the 1st". A reminder alerts at its time; a deadline ("by", "before", "due") gets an alert an hour before (a whole day: the morning before). With the Google Calendar sign-in it also goes **on your calendar** ("Due: submit the housing form"); without it, **Dock reminds you itself** with a card and a sound. Times are always in the future: "at 5" said at 10 pm is tomorrow, "the 1st" in late October is November 1st, and a passed "Friday noon" is next Friday. The list reads back with times: *"take the laundry out (tonight at 10:59 PM); call Mom (tomorrow at 5 PM); pay rent (due Nov 1)"*. Each note remembers the app you were in; open ones come back in focus sessions, the briefing and the night recap *(tested end to end; calendar events tested with a pretend calendar)*.
- **Google Calendar, Mac and Windows alike:** click **Sign in with Google** in the welcome window (the same sign-in connects Gmail): Google's sign-in page opens, you click Allow, and Dock reads every calendar you have ticked in Google (Meet links come straight from the events), and adds events only when you ask. Needs Dock registered once in Google Cloud ([docs/GOOGLE-CALENDAR.md](docs/GOOGLE-CALENDAR.md)). It stays on this computer *(Google reading tested with a pretend account: hidden and cancelled events skipped, Meet and Zoom links found)*. Then "what's on today?", "what's next?", a heads-up 10 minutes before each event, focus sessions that end 10 minutes before your next class, and **"get ready for stat class"**: the Meet/Zoom link, your stat310 folder or workspace, and related notes open in one go *(tested with a sample calendar: repeating class, Meet link, all-day event)*. Reminders and deadlines you ask for go on the calendar too.

## Models, cost and speed
| Job | Model | Cost |
|---|---|---|
| Understanding requests (picking the tool, asking when unsure) | Claude Haiku 4.5, with prompt caching | ~$0.0015 per request (~$0.01 for the first one after 5 idle minutes) |
| Pad buttons, summaries, recaps | Amazon Nova 2 Lite | ~$0.001 per request |
| "Where is…?" when the words don't match a menu item exactly | Claude Haiku 4.5 | ~$0.005 per question (exact matches are free) |
| Looking it up on the web (off for now: `DOCK_WEB_SEARCH=on`) | Nova 2 Lite + web grounding | ~$0.03 per search |
| Suggestions for an app | Claude Haiku 4.5 | ~$0.005–0.015 once per app, ever |
| Looking at the window for a control that isn't in the menus or labelled | Claude Haiku 4.5 (2 looks) | ~$0.005 each time |
| Tidy-up plans | Claude Haiku 4.5 | ~$0.01 per plan (with the start of each file) |
| Folder suggestion for a new download or a Save window | Amazon Nova 2 Lite | ~$0.001 each |
| Everything else (pad taps, opening, workspaces, moves, arrow, reading aloud, speech in Chrome, speech to text on the Mac with Whisper, the Mac's voice, server, tunnel) | none | Free |

- About **$0.10 per 100 requests**. Speed: 0.6–1.5 s for most requests, 2–4.5 s for multi-step ones, about 10 s for a tidy plan.
- Compared (routing test, 108 phrases, Oct 17): Haiku 4.5 with caching 108/108, median 0.82 s, ~$0.0016 per request; Nova 2 Lite 106/108 (it guessed on vague requests instead of asking), 0.69 s, ~$0.002. Nova Lite was cheapest but made things up, so it's not used.
- Change models with `DOCK_ROUTER_MODEL` / `DOCK_MODEL` / `DOCK_SMART_MODEL`. Prices come from third-party lists.

## Computer resources *(measured on an M1 Pro MacBook, 16 GB)*
| Part | RAM | CPU when idle | CPU while answering 10 requests |
|---|---|---|---|
| Dock server | 91–100 MB | 0.2% of one core | ~1% |
| Desktop agent | 80–91 MB | ~0% | ~0.5% |
| Cloudflare tunnel | 16–28 MB | 0.1% | 0.1% |
| **Total** | **≈190 MB** (about 1% of 16 GB) | **≈0.3%** | **≈1.5%** |

- RAM didn't grow during the heaviest requests (a tidy plan and a long summary), because the AI runs in the cloud (Bedrock), not on the Mac.
- The agent wakes every 30 s to note the app in front, and checks menus only while one is open. Battery impact is negligible.
- Starting Python directly instead of through the `uv` launcher saved about 50 MB (`scripts/dev.sh` does this now).
- The phone page is a normal Chrome tab. Speech recognition runs in Chrome.

## Under the hood (for judges)
- **MCP server:** Python MCP SDK 2.3.0, Streamable HTTP, protocol **2025-11-25**, bearer-token auth, 28 tools: `open_folder`, `find_files`, `open_file`, `open_app`, `arrange_windows`, `workspace`, `app_help`, `do_app_action`, `suggest_folders`, `put_in_folder`, `undo_last_action`, `set_folder_suggestions`, `read`, `get_recap`, `notes`, `get_schedule`, `get_ready`, `check_email`, `clean_up_email`, `add_email_todo`, `unsubscribe_email`, `get_briefing`, `improve_writing`, `apply_writing`, `search_web`, `start_focus_session`, `control_focus`, `focus_status` (voice macros removed Oct 17; 97 of 97 test phrases pick the right tool)
- **Simulated Alexa+:** phone → Bedrock picks tools → calls the MCP server over Streamable HTTP, exactly as Alexa+ would.
- **Desktop agent:** Python + macOS Accessibility (menus, pointing, clicking, windows, selected text) + Spotlight. It connects out to the server, so it works on campus Wi-Fi.

## Known limits
- App help and the pad use **the app in front** on the Mac.
- **Menus only** for now: no toolbar buttons or panels yet.
- Workspaces see **the current desktop only**. Unsaved documents can't come back.
- While Dock points at an item, that menu stays open for up to 8 s, and typing goes to the menu during that time. It closes as soon as Dock clicks.
- Saving a workspace may ask "allow Terminal to control Chrome / Safari / Finder" the first time.
- The newest phone screens (pad, tidy checklist, new-download card, reading, recap, **the new face/cards layout, landscape layout, dimming, the installed app, Focus sheet and countdown ring, camera presence**, "Try saying" examples, time saved) haven't been tried on a real phone yet.
- The phone address changes when Dock restarts, and also when the free Cloudflare tunnel drops (for example after the Mac sleeps). Dock checks the address every 30 s and opens a new one by itself after about 90 s of failures. You still have to scan the new QR code on the setup page; after about 30 s without a connection the phone tells you to. A stable address (AWS hosting or a named tunnel) would end this. *(Tested: froze the tunnel on purpose, and a new working address appeared in about 2 minutes.)*

## Not built yet
Toolbar buttons via screenshot + vision · AWS hosting (stable phone address) · Windows version (on hold) · real Alexa+ on the Echo Pop (waiting on access) · held Gmail messages

## Ideas next
1. **Find by what's inside a file:** "the PDF about linear regression" (small)
2. **Explain this error:** RStudio/VS Code errors in plain words (medium)
3. **Pick up where I left off:** reopen yesterday's files (small)
4. **Teach-me mode:** step-by-step pointing for "how do I export a movie" (medium)
5. **Buttons beyond menus:** window buttons and tabs through Accessibility (medium)
6. **Course workspaces automatically:** "open everything for stat310" (small)
