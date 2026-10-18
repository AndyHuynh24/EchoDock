# Dock Demo Script: "Alexa goes quiet when you work" (about 2:55, 3:00 max)

**Story:** Alexa helps all day at home, then goes silent the moment you sit down to work. Four everyday frictions, then the same four solved by Dock, in the same order. At night, Dock tells you what you got done and what's left, and Alexa says good night.

**Honesty rule:** a real Echo Pop only does what real Alexa does today (music, good night, lights). Every Dock answer comes from Dock (Mac or phone, the simulated Alexa+) and has a caption saying so. Once the "One Dock" Alexa Skill is built (planned), the lines marked **[Skill]** move to the real Echo Pop.

## Act 1: Alexa all day, except at work (0:00–0:45)

Time-of-day stamps in the corner tell the story of one day.

| Time | Shot | Say / do | On screen / edit |
|---|---|---|---|
| 0:00 | **7:30 AM**, full color, waking up | **You:** "Alexa, what's the weather today?" | Real Alexa answers. Day bar appears at the bottom (see Editing) |
| 0:05 | **8:30 AM**, getting ready | **You:** "Alexa, play some lo-fi." | Music starts; it becomes the video's soundtrack |
| 0:09 | **9:00 AM**, you sit at the desk and open the laptop | **You:** "Alexa, stop." | Music stops. **The color drains out of everything except the Echo Pop** (1 s) |
| 0:12 | Locked shot of the gray desk, the Echo Pop the only color, its ring dark | **VO:** "Alexa is with me all morning and all evening. But from nine to six, where I spend most of my day, at my computer, it goes quiet." | The day bar's work hours stay gray |
| 0:21 | **10:12 AM**, Friction 1: clicking Documents › school › CS589… | (sigh) | Gray. Counter: *0:14 to find one folder* |
| 0:27 | **11:40 AM**, Friction 2: a Save window, scrolling through folders | | Gray. *Where does stat310 homework go again?* |
| 0:33 | **1:05 PM**, Friction 3: RStudio menus, then googling | | Gray. *I know it's in here somewhere.* |
| 0:38 | **2:30 PM**, Friction 4: the phone, Instagram | (look up: the clock has jumped) | Gray. *…and then my phone.* Hold one beat of silence |

## Act 2: Dock (0:45–2:10)

| Time | Shot | Say / do | On screen |
|---|---|---|---|
| 0:45 | Instead of scrolling, you put the phone into the dock beside the Echo Pop | Dock's face opens its eyes and smiles. **Color ripples out from the phone** across the desk, the Echo Pop and the Mac screen; the music comes back; the day bar's gray hours light up | **VO:** "So I built Dock. It brings Alexa to my computer and makes it an assistant for my whole day. My Echo Pop has no screen, so my phone becomes its face." Title: **Dock** |
| 0:52 | **Fix 1:** press ⌥Space | **You:** "Open my CS 589 folder." | The right folder opens. Counter: *1 s* |
| 1:00 | **Fix 2:** download hw4.pdf, and the Save window opens | Card on the phone: *Save it in stat310 › homework?* **You:** "Save it there." | An arrow at the Where menu, then the file saves in the right place |
| 1:14 | **Fix 3:** RStudio | **You:** "How do I run just this chunk?" | A spoken answer, the menu opening by itself, an orange arrow, and ⇧⌘↩ big on the phone |
| 1:25 | | **You:** "Do it." | The chunk runs |
| 1:29 | A command instead of a question | **You:** "Put Chrome on the left and RStudio on the right." | The windows snap into place. *Questions get shown. Commands just happen.* *(cut first if over time)* |
| 1:38 | **Fix 4:** the phone stays in the dock | **You:** "Focus on stat310 homework for 50 minutes." | Timer and face on the phone |
| 1:45 | You get up and leave | | *Paused: you're away.* You come back and it resumes |
| 1:53 | A thought mid-work | **You:** "Note: ask the professor about question 3." | A note card *(pays off at night)* |
| 1:58 | Quick montage | (working) | Timer running, homework done, phone untouched |

## Act 3: How it works (2:10–2:27)

Architecture diagram, with Dock's server log scrolling beside it (`initialize` 2025-11-25, `tools/call open_folder`, `tools/call app_help`).

**VO:** "Dock is an MCP server, the kind of server Alexa+ add-ons talk to. Here a simulated Alexa+ calls it over Streamable HTTP; an Alexa+ add-on would call the exact same tools. A small agent on the Mac does the work: it reads the app's real menus, and looks at the screen only when it has to. Open source, about a fifth of a cent per request."

## Act 4: Good night (2:27–2:55)

| Time | Shot | Say / do | On screen |
|---|---|---|---|
| 2:27 | **11:00 PM**, evening light, the laptop closing | **You** (to the docked phone): "What did I get done today?" **[Skill]:** "Alexa, ask One Dock what I got done today." | **Dock:** "You focused 2 hours on stat310 and finished homework 4. Still left: ask the professor about question 3. Tomorrow: CS589 at 10." *Simulated Alexa+: the same MCP tools.* (drop the caption once it's the real skill) |
| 2:42 | You take the phone out of the dock and walk to the Echo Pop | **You:** "Alexa, good night." | Real Alexa: the lights go off. Just before you pick up the phone, Dock's face says *Good night* and closes its eyes *(to build: sleepy face after the evening recap)* |
| 2:49 | Black screen | | **Dock: Alexa, at your desk.** Repo link. Small print (until the skill exists): *With Alexa+ add-ons, this comes straight from your Echo.* |

## Editing guide (free: DaVinci Resolve or CapCut)

**The idea: color means "Alexa is helping".** Morning and night are in color. The work hours are gray, because Alexa is quiet. Dock brings the color back to the desk.

- **Color drain at 9:00 AM:** keyframe saturation from 100 to 0 and exposure down about 1 stop over 1 s, with a soft vignette. Mask the Echo Pop so it stays in color.
  - Resolve: Color page, a circle Power Window on the Echo Pop, invert it, then saturation 0.
  - CapCut: duplicate the clip, mask the top copy to the Echo, desaturate the bottom copy.
- **Not pitch black:** the frictions must stay readable. Use gray and slightly dim, not black. The screen-recording close-ups are gray but at normal brightness.
- **Film the desk on a tripod, never moving.** Then one mask works for every desk shot. Handheld shots would need mask tracking, which is slow and wobbly.
- **The Echo's ring stays dark while gray** (Alexa is quiet). Don't add a fake glowing ring later: the real Echo doesn't react to Dock until the skill exists.
- **Color returns at 0:45:** a radial mask that starts at the phone's face and grows over the whole frame in 12–18 frames, with a soft chime. Use this effect once only. Don't repeat it on other cuts.
- **Sound tells the same story:** the lo-fi music is Alexa's. At "Alexa, stop" it ends. During the frictions there is only room tone, mouse clicks, a ticking clock and a sigh. The music returns with the color.
- **Day bar:** a thin 24-hour bar at the bottom of the frame, from 6 AM to midnight. Morning and evening glow in Alexa cyan; 9 to 6 is gray. At 0:45 the gray part fills with color from left to right. Hide it during Act 2 so it doesn't distract, and bring it back, fully lit, in the night scene.
- **Time stamps** (7:30 AM, 10:12 AM, …) sit small in a top corner and jump forward with each cut.
- **Statistics:** use a number like "hours a day at a computer" only if you can cite a source in the description. Otherwise let the day bar say it.

## The phone as the face
The Echo Pop has no screen, so the docked phone is Dock's face, and every scene should show it reacting:
- it **listens** while you talk (cyan),
- it **thinks** while Dock works,
- a quick **done** smile, with the answer or the shortcut card big on the screen,
- **away / paused** when you leave the desk,
- **sleepy** at night *(to build)*.

Keep the phone in shot next to the Echo Pop in every Act 2 scene, so the face and the arrow on the Mac are both visible. It's Dock's face (not Alexa's), so don't caption it as Alexa.

## Test list (run each 3 times before recording)

| # | Say / do | Must happen | Status |
|---|---|---|---|
| 1 | "Open my CS 589 folder." (⌥Space) | Documents/…/CS589 opens in about 1 s | tested before |
| 2 | Download hw4.pdf from Chrome (with "Ask where to save each file" on) | Card *Save it in stat310 › homework?* within about 2 s; "save it there" saves it there | tested before |
| 3 | In RStudio: "How do I run just this chunk?" | Arrow on Run Current Chunk, ⇧⌘↩ on the phone | **test** |
| 4 | "Do it." | The chunk runs | **test** |
| 5 | "Put Chrome on the left and RStudio on the right." | Both snap into halves | tested with other apps |
| 6 | "Focus on stat310 homework for 50 minutes." | Timer on the phone; walking away pauses it | **test the camera on the real phone** |
| 7 | "Note: ask the professor about question 3." | Note saved | tested before |
| 8 | "What did I get done today?" | Mentions focus time, homework, **the open note**, **tomorrow's class** | **test** (calendar must be connected) |
| 9 | "Alexa, good night." | The Echo's routine turns the lights off | **set up a routine and a smart light or plug** |

## Setup before recording
- Folder suggestions **on** (gear › Settings), so the Save card appears without the "Want Dock to suggest a folder?" step.
- Signed in with Google (Calendar and Gmail), with a real class tomorrow.
- Phone in Do Not Disturb, Dock full screen in the dock. Mac: nothing personal on screen, Finder closed.
- One warm-up request so the speech model and AI are loaded.
- Film both the Mac screen and the phone in shot when the arrow appears. Record the screen separately for close-ups.

## Tips
- Captions for every spoken line (judges often watch muted).
- Keep the corner counter: "0:14" against "1 s" shows the value instantly.
- The note at 1:53 coming back at 2:27 is "state across sessions", one of Amazon's own examples of a creative Alexa+ idea. Keep it even if other scenes go.
- Over time? Cut the window arrangement (1:29) first, then shorten Act 3.
- If a take fails, record it again. Never fix answers in editing.
