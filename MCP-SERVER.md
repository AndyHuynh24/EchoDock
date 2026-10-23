# Dock MCP server

**Alexa+ for your desk.** Ask out loud, and Dock controls your Mac and helps you *inside whatever app you're using*: it says where a feature is, points at it on screen, clicks it when you say "do it", and turns your phone into a second screen and shortcut pad for that app.

> Other Mac MCP servers give an AI **hands**. Dock helps **you**: it shows you first, and acts when you say so.

| | |
|---|---|
| Protocol | MCP **2025-11-25** (checked: `initialize` returns `"protocolVersion":"2025-11-25"`) |
| Transport | **Streamable HTTP** at `/mcp`, stateless, JSON responses |
| SDK | Official MCP Python SDK 2.3.0 (`mcp.server.MCPServer`) |
| Tools | **30**, in 7 groups (below) |
| Auth | Bearer token on `/mcp` (no token: HTTP 401) |
| MCP client used in the demo | Simulated Alexa+: the phone web page → an Amazon Bedrock agent (Claude Haiku 4.5) that calls `initialize`, `tools/list` and `tools/call` on `/mcp` over Streamable HTTP, exactly like Alexa+ would |
| Speed | Menu answers in under 1 s. A full spoken turn from the phone takes about 1–1.5 s |
| Cost | About $0.001 per spoken request. Many features need no AI at all |
| Footprint | Under 200 MB of RAM in total, close to 0% CPU when idle |

---

## Why Dock stands out

1. **Help inside *any* Mac app, by voice, with exact answers.** Dock reads the app's real menus through macOS Accessibility, so the item name and shortcut match *your* version of the app. Loose wording works too ("how do I cut this clip in two?" → *Modify › Split Clip, ⌘B*). There's no window sharing, no chat box, and no screenshots by default.
2. **Every answer shows up in three places.** You hear it, an orange arrow points at the item on your screen, and a card appears on the phone. Then **"do it"** clicks that exact item.
3. **It suggests, you decide.** Select text and say "fix the grammar": a card shows the changes marked, and nothing changes until you tap **Replace**, **Insert below** or **Change more**. "Google how to cite a website" offers the search with a **Search** button. "Clean up my inbox" shows a checklist first. The phone also shows **how much time Dock saved you this week**.
4. **A focus mode that understands your goal.** "Focus on stat310 homework for 50 minutes" opens the matching workspace. The phone camera notices when you step away (the video never leaves the phone). Dock says "welcome back, you were in hw_03.Rmd" and brings the file back. It knows a dplyr tutorial on YouTube helps with stat310 but MrBeast doesn't, and it ends with proof of work.
5. **It remembers you across sessions.** Workspaces, to-dos and reminders, time saved, focus history and per-app shortcut pads are all kept between restarts.
6. **Safe by design.** Dock has a fixed allowlist of actions: no shell commands and no deleting. Risky menu items (Delete, Quit, Erase…) are never clicked by voice. Files move only after you agree, and the move can be undone. Screen text is read only when you ask.

### How this fits the judging criteria
| Criterion | What Dock shows |
|---|---|
| **Tech implementation** | A real MCP server on spec 2025-11-25 with Streamable HTTP. A real MCP client (the Bedrock agent) drives it. Its 30 tools reach the Mac through an outbound WebSocket to a desktop agent (PyObjC + Accessibility API) |
| **Design** | Answers you hear, an arrow on screen, and the phone as a second screen, so nothing covers your work. "Try saying…" chips show new users what to ask. Every reply is one or two short spoken sentences |
| **Potential impact** | Anyone who learns new software: students in RStudio, creators in iMovie, office workers. It works in any Mac app with menus, and it's free to run apart from about $0.001 per AI request |
| **Quality of the idea** | It matches the creative directions the hackathon lists: **agentic workflows** (multi-step requests, email clean-up, writing suggestions), **state across sessions** (workspaces, reminders, focus history), and **cards** (phone and Mac cards, shortcut pad, focus report) |

---

## How it works

```
 You speak ──▶ phone web app (simulated Alexa+, speech-to-text)
                    │  POST /api/voice
                    ▼
          Bedrock agent = MCP client ──Streamable HTTP──▶  Dock MCP server  /mcp
          (Haiku 4.5 picks tools)     initialize,          30 tools, state, Bedrock
                    ▲                 tools/list,                │
                    │ spoken reply    tools/call                 │ WebSocket (the agent dials out)
                    │                                            ▼
               phone speaks  ◀── cards, pad, timer ──  Desktop agent on the Mac
                                  (WebSocket)           menus via Accessibility, arrow overlay,
                                                        open/find files, workspaces, text
```

- **With real Alexa+**, Alexa+ would be the MCP client calling the same `/mcp` endpoint, with no changes to the server. The hackathon FAQ confirms that Alexa+ builder tools aren't available to participants, and that a web page acting as an MCP client is the intended path.
- **Two outputs per tool.** Each tool returns short text to speak, *and* pushes what belongs on a screen (cards, the arrow, checklists, charts) to the phone and Mac. Alexa+ can't draw on our phone, so the server does it.
- **The laptop dials out**, so it works on campus Wi-Fi with no port forwarding.

---

## The 30 tools
(Merged from 32 to 20 on Oct 16, so the AI has fewer look-alike tools to choose from; everyday tools were added since, and voice macros were removed on Oct 17. In a 97-phrase routing test, all 97 pick the right tool.)

### Help inside apps
| Tool | Say | What happens |
|---|---|---|
| `app_help(question, do_it)` | "Where's the split tool?" / "split the screen" | Finds the menu item in the app in front, says where it is and its shortcut, points at it on screen and shows a phone card. Not in the menus: the window's labelled buttons, then a look at a screenshot of just that window. `do_it` also clicks it. It mentions greyed-out items; if it can't find it, it offers a Google search |
| `do_app_action()` | "Do it" | Clicks the item Dock just pointed to, in the same app only. Risky items are refused |

### Computer control
| Tool | Say | What happens |
|---|---|---|
| `open_folder(name)` | "Open my stat310 folder" | Finds folders anywhere in your home folder, iCloud and cloud drives |
| `find_files(name, kind, folder, days)` | "What PDFs do I have in stat 310?" | Understands folder words, file types and loose dates ("yesterday", "this week") |
| `open_file(path, show_in_finder)` | "Open the newest one" / "show it in Finder" | Never opens anything that could run a program |
| `open_app(name)` | "Open VS Code" | Understands spoken app names |
| `workspace(action: save/open/list, name)` | "Remember this workspace as Study" / "open my Study workspace" | Saves apps, documents, Chrome/Safari tabs, Finder folders and window positions, and brings them back without duplicating tabs |

### Everyday desk basics
| Tool | Say | What happens |
|---|---|---|
| `arrange_windows(layout, screen, hide_others)` | "Put Chrome on the left and Notes on the right" / "make this full screen" / "move this to my other screen" | Moves and sizes windows (halves, thirds, quarters, full), opens apps that aren't open yet, never guesses an app you don't have |
| `close_windows(app, which)` | "Close this window" / "close all the Finder windows" / "close all windows" | Closes windows with their own close button; unsaved documents still ask to save (Mac only for now) |
| `notes(action, text, when, deadline)` | "Note: …" / "remind me to call Mom at 5" / "I need to submit the form by Friday noon" / "what's on my list?" / "cross off …" | Dock's to-do list. With a time it also goes on the Google calendar (a reminder at that time, or a deadline with an alert an hour before), or Dock reminds the user itself |
| `get_schedule(day: today/tomorrow/next)` | "What's on today?" / "when's my next class?" | Reads Google Calendar (through "Sign in with Google", repeating events included); same on Mac and Windows |
| `get_ready(for_what)` | "Get ready for stat class" / "get ready" | Opens the event's Meet/Zoom link and the matching folder or workspace (STAT 310 → stat310), and mentions related notes |
| `check_email(period)` | "What did I miss?" / "any new email?" / "anything important?" | Unread email since the last focus session started (or today, or this week), sorted by the AI into important, updates, promotions and spam. Says one short line per important email (urgent first) and counts the rest; the list is on the phone. Gmail, through the same "Sign in with Google". During focus, mail waits, except from people on the let-through list or (from real people, not newsletters) mail the AI calls urgent. Each morning a card offers a quick look |
| `clean_up_email(confirm)` | "Clean up my inbox" / "delete the spam" / "organize my email", then "yes" | Proposes a checklist (spam and promotions to the Trash, updates like receipts filed into folders, one-tap Unsubscribe on promotions) and changes nothing until the user taps Clean up or says yes |
| `add_email_todo(text)` | "Yes, add it" / "put it on my calendar" after a to-do from email | The to-do goes on the list and, with its deadline, on the calendar |
| `unsubscribe_email(sender)` | "Unsubscribe from Old Navy" / "stop these DoorDash emails" | The sender's standard one-click unsubscribe (RFC 8058), or their unsubscribe page opened on the Mac. Never for spam, never by sending an email |
| `get_briefing()` | "Good morning" / "brief me" / "what does my day look like?" | Today's calendar, the important email (with to-dos it can add to the list) and open notes, in one card and a few sentences. Also offered once each morning |
| `improve_writing(how)` | Select text, then "fix the grammar" / "check this for typos" / "make this more professional" / "make it shorter" / "translate this to Spanish" | Shows a suggestion first (changes marked, on the phone and the Mac), for the selection in any app (documents, email, web forms); asked again, it changes the suggestion further |
| `apply_writing(where)` | "Use it" / "put it below" / "never mind" | Replaces the selection with the suggestion, or adds it under the original, in place with no copy and paste; Command Z undoes it |
| `search_web(query, go)` | "Google how to cite a website in APA" / "look up the library hours", or anything Dock can't do or answer | Offers the search first (a "Search Google?" card with Search and Not now); only Search or "yes" (`go`) opens it, in a new tab of the default browser |

### Ask about your stuff (RAG)
| Tool | Say | What happens |
|---|---|---|
| `search_my_stuff(question, kind, since_days, open_source)` | "What's the Wi-Fi password the landlord sent?" / "when is the CS589 project due?" / "how many late days do I get?", then "open it" | Answers from your own documents, recent email, notes and calendar, and says where the answer came from. Hybrid search (Titan embeddings in sqlite-vec + FTS5 keywords, merged by reciprocal rank fusion), then Claude Haiku answers only from the best excerpts or says it couldn't find it. Indexes on first use, refreshes every 30 minutes, all kept on the computer. Eval: 22/22 correct, 3/3 "not found" on questions with no answer |

### Files into folders
| Tool | Say | What happens |
|---|---|---|
| `suggest_folders(all_downloads)` | "Where should this go?" / "help me tidy my downloads" | One file (the open Save window, or else the newest download), or the whole Downloads folder with questions about unclear files. **Moves nothing** |
| `put_in_folder(moves, folder, new_folder)` | "Yes, move it" / "save it there" / "put it on my Desktop" | Finishes the open Save window in a folder, or moves downloads. Only after you agree; never overwrites |
| `undo_last_action()` | "Undo" | Puts the files back |
| `set_folder_suggestions(on)` | "Turn on folder suggestions" | Automatic suggestions for every download and Save window. Off by default, since each one uses a little AI |

### Reading and your day
| Tool | Say | What happens |
|---|---|---|
| `read(how: summarize/aloud, path)` | "Summarize this" / "read this to me" | The selected text, the open document or PDF, or a file. Aloud: on the phone speaker or the Mac, with a Stop button |
| `get_recap(period: today/yesterday/week)` | "What did I work on today?" / "how was my week?" / "how much time did Dock save me?" | Today or yesterday: time per app, files worked on, what you asked Dock. Week: focus sessions and time Dock saved. Activity data stays on your Mac |

### Focus mode (optional)
| Tool | Say | What happens |
|---|---|---|
| `start_focus_session(goal, minutes, workspace)` | "Focus on stat310 homework for 50 minutes" | Starts the timer and face, opens the matching workspace, and turns on camera presence and gentle drift nudges |
| `control_focus(action: pause/resume/break/end, minutes, finished_goal)` | "Pause" / "I'm back" / "take a break" / "end my session, I finished" | End gives a proof-of-work report; a break shows flashcards of shortcuts you asked Dock about |
| `focus_status()` | "How's my session going?" | |

**Not a tool, but always on:** the **shortcut pad** (phone buttons for the app in front, picked once per app and then free), and **"Try saying…" chips**.

### How the tools are written for a voice assistant
- **Descriptions say *when* to use each tool**, with example phrases, because Alexa+ picks tools by reading them.
- **Spoken text stays short.** Details go to the phone.
- **Failures are real MCP errors** (`ToolError`), so the assistant never claims "done" when something failed.
- **Context lives on the server.** "Do it", "show the newest one in Finder" and "save that" work even if the client forgets the previous turn.
- **Two-step tools for anything that changes files:** plan first, then act only after you agree.

---

## Try it yourself (about 1 minute)

```bash
./scripts/start.sh                     # starts the server, the desktop agent and the phone tunnel
TOKEN=$(cat .dock-token)

# initialize: shows protocolVersion 2025-11-25
curl -s -X POST localhost:8000/mcp -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# tools/list: the 30 tools
curl -s -X POST localhost:8000/mcp -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-11-25" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

Any MCP client that supports Streamable HTTP and custom headers can connect to `http://localhost:8000/mcp` with `Authorization: Bearer <token>`. The phone app (the setup page has a QR code) is the full experience.

---

## Related work, honestly

| Project | What it does | How Dock is different |
|---|---|---|
| [Peekaboo](https://github.com/openclaw/Peekaboo), [macpilot-mcp](https://github.com/passerby2049/macpilot-mcp), [mac-mcp-server](https://glama.ai/mcp/servers/ryota-murakami/mac-mcp-server), [drews-mac-control-mcp](https://github.com/drewster99/drews-mac-control-mcp), [mcp-server-macos-use](https://mcp.so/servers/mcp-server-macos-use) | MCP servers that let an AI agent click Mac apps, often through the same Accessibility menus | These are built for an **AI to drive your Mac**. Dock is built for **the person at the desk**: it tells you, points, teaches the shortcut and acts only when you say "do it". It adds the phone pad, writing and search suggestions you approve, email help and focus mode |
| Microsoft Copilot Vision (Highlights) | Highlights where to click in a window you share | Windows only, needs a sharing step, and guesses from pixels. Dock reads the real menus, so it's exact |
| Computer-use agents (Claude, ChatGPT agent, Simular…) | General tasks through screenshots | They take minutes and can misclick. Dock does menu actions directly in about 1 s |

## Honest limits
- macOS only for now. The server and phone app are cross-platform, and a Windows desktop agent is planned.
- App help covers **menus**. Toolbar-only buttons are next (Accessibility first, then vision).
- No real Alexa+ device: the builder tools are partner-only. The same `/mcp` endpoint is ready for it.
- Single user. Account linking (OAuth) would come before a multi-user deployment.

See [CAPABILITIES.md](CAPABILITIES.md) for tested examples and measurements of every feature.
