# Dock — Getting Ready Checklist

Everything I need from you before we start building. I already checked your Mac, so some items are done.

## At a glance

| # | Item | Status | Time |
|---|---|---|---|
| 1 | Hackathon deadline, rules, overview | ✅ Done: pre-existing code allowed, video ≤ 3 min | — |
| 2 | Laptop OS | ✅ Done: macOS 26.2, Apple Silicon (M-series) | — |
| 3 | Demo app for app help | 🟡 Pick one: iMovie and CapCut are both installed | 5 min |
| 4 | Phone model | ✅ Done: Galaxy Z Fold 8 (Android, use Chrome) | — |
| 5 | Alexa+ on your Echo Pop | 🟡 Optional: see the note below. We're going phone-first | 5 min |
| 6 | Amazon Developer account + Alexa AI CLI | 🟡 Optional: invite-only, only if organizers give access | 5 min |
| 7 | AWS account, login, Bedrock access | 🟡 AWS CLI installed but not logged in | 20 min |
| 8 | Domain name | ⬜ Optional, can wait until day 6 | 10 min |
| 9 | Quick decisions (users, browser, team) | ⬜ To do | 2 min |
| 10 | 3D printer | ⬜ Optional | 5 min |
| 11 | Dev tools on the Mac | 🟡 Only `cloudflared` is missing | 2 min |
| 12 | GitHub | ✅ Done: logged in as `AndyHuynh24` | — |

When you finish an item, paste the **"Send me"** line for it into the chat.

---

## ⚠️ What I found about Alexa+ access (read this first)
- **What Alexa+ is:** Amazon's new AI version of Alexa. It runs on Echo devices, the Alexa app and Alexa.com. Builders connect their own services to it as **add-ons**. For us, that means an MCP server.
- **Real add-ons are invite-only right now.** The Alexa+ for Builders page says it's "available to select partners working directly with our team." The setup guide even needs an AWS role that an Amazon Solutions Architect gives you, and the `alexa-ai` CLI is installed from Amazon's private package store.
- **The track explicitly allows the simulated path:** *"You can simulate an Alexa+ experience using your preferred agentic tools via a web app."* That's our phone-first plan.
- **What still counts:** a real MCP server using Streamable HTTP (done: ours negotiates spec 2025-11-25) and a simulated Alexa+ web app that calls it.
- **Optional, 5 min:** ask the organizers on the Devpost **Discussions/Updates** tab or the hackathon Discord whether participants can get Alexa+ for Builders preview access. If yes, items 5–6 apply. If not, skip them.
- The guide link you found (`/docs/adbt/get-started`) is for **Fire TV / Vega** builder tools, not Alexa+.

---

## 1. Hackathon deadline, rules, overview  ✅ (you answered: pre-existing code OK, video ≤ 3 min)
Most important: one source says the deadline is **Oct 23, 2026**, which is only 9 days away.

1. Open https://amazonappdev2026.devpost.com in your browser. (I can't open Devpost: it blocks me.)
2. On the **Overview** tab, find the **submission deadline and its time zone**.
3. Open **Rules** (usually linked at the bottom) and look for:
   - **pre-existing code**: may we use code written before the event?
   - **demo video length** (one source says under 3 minutes)
   - **judging criteria**
4. Open the **Resources** tab and look for:
   - any **Alexa+ builder access** or sign-up form
   - any **AWS credits** form
5. Copy the overview text into the chat (the one you mentioned, which didn't come through).

**Send me:** deadline + time zone, the pre-existing code rule, video length, and the pasted overview.

---

## 2. Laptop OS  ✅
Already checked: **macOS 26.2, Apple Silicon (arm64)**. Nothing to do.

---

## 3. Demo app for app help  🟡
You have both **iMovie** and **CapCut**. I recommend **iMovie**: Apple apps expose their menus reliably, which is what Dock reads.

1. Open **iMovie** → create a new **Movie** project → drag in any short video clip.
2. Click the clip in the timeline, then open the **Modify** menu at the top of the screen.
3. Check that **Split Clip** is there with the shortcut **⌘B**.
4. Optional: open **CapCut** and look at its top menu bar. Does it have many menu items, or just a few? (A few means CapCut hides most tools from Dock.)

**Send me:** "iMovie has Split Clip ⌘B: yes/no" and which app you want.

---

## 4. Phone  ✅ Galaxy Z Fold 8
Chrome on Android supports everything we need: camera, keep-screen-awake, speech-to-text, and screen pinning (Settings → Security → Pin app).

(Original steps, for reference:)
- **iPhone:** Settings → General → About → write down **Model Name** and **iOS Version**.
- **Android:** Settings → About phone → write down the **model** and **Android version**. Also note which browser you use (Chrome?).

**Send me:** e.g. "iPhone 15, iOS 26.1".

---

## 5. Alexa+ on your Echo Pop  ⬜
1. Make sure the Echo Pop is set up in the **Alexa app** on your phone.
2. Ask it: **"Alexa, are you Alexa+?"** and listen to the answer.
3. Also look in the Alexa app for **Alexa+** branding or settings.
4. If you don't have Alexa+ yet, check the hackathon **Resources** page (item 1) for how builders get access.
5. Write down which **Amazon account (email)** the Echo uses. You'll need the same account in item 6.

**Send me:** "Alexa+ on Echo: yes/no/not sure", and whether the Resources page mentions access.

> If this turns out to be hard, that's fine. We go phone-first (the simulated path), as agreed.

---

## 6. Amazon Developer account + Alexa AI CLI  ⬜
1. Go to https://developer.amazon.com and sign in with the **same Amazon account as your Echo Pop** (from item 5). This is what usually lets you test your own add-on on your own device.
2. Accept the developer agreement if asked.
3. Open the MCP quickstart: https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html
4. Follow its **"install the Alexa AI CLI"** step and copy the install command from that page exactly. (It probably uses Node, which you already have, v26.)
5. Check that it installed. In Terminal:
   ```
   alexa-ai --help
   ```
6. If the page says you need to **request access** or join a preview, do that now. Approval can take time.

**Send me:** "alexa-ai installed: yes/no" plus any access-request message you saw.

---

## 7. AWS account, login, Bedrock access  🟡
The AWS CLI is installed (v2.37), but **no account is logged in**.

**a) Account**
1. If you don't have one, sign up at https://aws.amazon.com (needs a card; we'll stay cheap).
2. If the Resources page (item 1) offers **AWS credits**, apply now.
3. Set a spending alert so there are no surprises: AWS Console → **Billing and Cost Management** → **Budgets** → **Create budget** → "Monthly cost budget" → **$10** → your email.

**b) Log in from Terminal**
```
aws login
```
A browser window opens. Sign in and approve. Then check it worked:
```
aws sts get-caller-identity
```
You should see your account number.

**c) Pick a region**
Use **us-east-1 (N. Virginia)**. It has the widest choice of Bedrock models. We'll put everything there.
```
aws configure set region us-east-1
```

**d) Bedrock model access**
1. AWS Console → top-right region → **US East (N. Virginia)**.
2. Search **Bedrock** → open **Playgrounds → Chat**.
3. Pick an **Anthropic Claude** model (a Haiku or Sonnet one) and send "hello".
4. If it asks for a **use-case form** (first-time Anthropic use), fill it in. It's short.
5. Also try an **Amazon Nova** model (e.g. Nova Lite) and send "hello".

**Send me:** "aws sts works: yes/no", the region, and "Claude reply: yes/no, Nova reply: yes/no".

---

## 8. Domain name  ⬜ (optional, can wait until day 6)
Days 1–5 use a free temporary tunnel address, so this isn't urgent. When we move to AWS on day 6:
- **Easiest:** AWS Console → **Route 53** → **Registered domains** → **Register domain**. Pick something cheap (e.g. `.click` or `.link` are a few dollars a year; `.com` is about $14).
- **Free option:** a free subdomain from https://www.duckdns.org. It works fine with our HTTPS setup.

**Send me:** the domain you picked, or "use DuckDNS".

---

## 9. Quick decisions  ⬜
Just answer these:
- **Users:** only you for the hackathon (simplest), or should judges be able to install it too?
- **Browser** for saving and reopening tabs: **Chrome** or **Safari**? (You have both.)
- **Team:** solo, or teammates? If teammates, their GitHub usernames.

---

## 10. 3D printer  ⬜ (optional)
With 9 days left, a store-bought phone stand next to the Echo Pop is fine for the demo.
- If you want a print: check your campus **makerspace / library / engineering lab** hours and whether you can book a printer this week. A first print takes several hours.

**Send me:** "printer: yes (where/when) / no".

---

## 11. Dev tools on the Mac  🟡
Already installed: Homebrew, Python 3.12, Node 26, git, GitHub CLI, AWS CLI.
Missing: **cloudflared** (gives our server a temporary public HTTPS address on days 1–5).
```
brew install cloudflared
cloudflared --version
```

**Send me:** "cloudflared installed".

---

## 12. GitHub  ✅
Already logged in as **AndyHuynh24**. When we start, I'll create the repo. Reviewers get added **at submission time**, from the repo's **Settings → Collaborators** page.

---

### Shortest path to start day 1
Items **1, 3, 7 and 11** are enough to start building today. Items 5 and 6 can run in parallel, since Alexa+ access may take time to approve.
