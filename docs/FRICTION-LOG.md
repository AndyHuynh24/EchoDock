# Friction log: building Dock (Alexa+ track)

What we tried with Amazon's tools, what worked, what didn't, and the workarounds. Dates are 2026.

## Alexa+ (MCP Toolkit, alexa-ai CLI, Web Simulator)

| What we tried | What happened | Workaround | Suggestion |
|---|---|---|---|
| Follow the MCP Toolkit quickstart to register our MCP server as an Alexa+ add-on (Oct 14) | The `@alexa-ai/cli` package is served from a private CodeArtifact repository, and setup needs an AWS role from an Amazon Solutions Architect. There was no way to install the CLI or open the Web Simulator. The FAQ later confirmed that no participant can get access. | Built the self-hosted MCP server anyway (Streamable HTTP, spec 2025-11-25), plus our own clients that act like Alexa+: a Bedrock agent behind a phone web app and a Mac menu-bar app, both calling the server's `initialize` / `tools/list` / `tools/call`. | Say clearly on the track page and the quickstart that the toolkit is partner-only, and offer a public simulator or a "conformance check" endpoint, so builders can see whether Alexa+ would pick their tools. |
| Plan for real-device limits from the docs | The docs mention add-on response time limits (about 500 ms) and OAuth 2.1 with PKCE for account linking. We couldn't test either, so we couldn't tell whether our ~1 s menu answers would be acceptable. | Kept tool answers short and fast (menu lookups run before any AI call), and kept slow work out of the reply. | A public test harness that times a tool call the way Alexa+ does would let builders tune before getting access. |
| Decide whether "Alexa, do it" follow-ups reach the same add-on | Unknown without the simulator. | The server remembers the last thing it pointed at, so "do it" works no matter which client sends it. | Document how follow-up turns are routed to add-ons. |

## Amazon Bedrock

| What we tried | What happened | Workaround | Suggestion |
|---|---|---|---|
| Use `aws login` credentials with boto3 (Oct 15 and Oct 16) | The login session expired twice during development. Every AI call then failed with `LoginRefreshRequired` deep inside botocore's credential refresh, with a long traceback. The app could only say "something went wrong". | Dock now detects that error and says: "My AI login has expired. On the Mac, open Terminal and run aws login." | Longer sessions for `aws login`, or a short, clear exception message that is easy to catch. |
| The AWS MCP server in our coding assistant | It failed to start with "No AWS credentials available" even though `aws login` worked for the AWS CLI and boto3. | Didn't use it. | Support the `aws login` credential provider in the AWS MCP server. |
| Amazon Nova 2 Lite for tool calling | Worked well: in our tests it handled multi-step requests about as well as Claude Haiku 4.5 for roughly a quarter of the price. It has to be called through the inference profile ID (`us.amazon.nova-2-lite-v1:0`), not the base model ID. It sometimes puts `<thinking>…</thinking>` in the text reply, which a voice assistant must not read out. | We strip `<thinking>` blocks before speaking. | Mention the `us.` profile ID on the model card's first screen; an option to never return thinking text. |
| Prompt caching on Bedrock (Converse `cachePoint`) for the tool picker | Easy and worth it: one `cachePoint` after the tools and one after the fixed instructions, and ~7,100 of ~7,600 tokens per request were read from cache. That made Claude Haiku 4.5 cheaper per request than Nova 2 Lite without caching. The cache only lasts 5 minutes, so the first request after a pause costs more. | Put the request's changing facts (the app in front, the time) in a system block after the cache point. | A longer cache time for apps that are used now and then, like a voice assistant. |
| Amazon Nova Lite (v1) | It invented file paths and skipped steps in multi-step tool use. | Switched to Nova 2 Lite. | — |
| Nova 2 Lite picking one menu item out of 300+ ("open the terminal" in VS Code) | It often picked a related item instead of the right one ("Split Terminal"). | Claude Haiku 4.5 on Bedrock for that one job; it got all 7 of our tricky test questions right. | — |
| Nova web grounding (`nova_grounding` system tool) for "how do I translate a page in Chrome?" | Worked nicely: 3–5 s, and it cited Google's own help page. But the price wasn't easy to find on the official pricing page (we only found ~$0.03 per request on a third-party site). The answer comes back as many small `citationsContent` blocks between text blocks, and the search result itself shows as "[HIDDEN]". | Joined the text blocks and kept the first source's site. Turned the feature off for now because of the cost. | Put the grounding price next to the model prices; a simple "answer + sources" shape. |

## Amazon S3 (hosting the installable phone app)

| What we tried | What happened | Workaround | Suggestion |
|---|---|---|---|
| Host the phone web app (a PWA) at a fixed HTTPS address from S3, so the link never changes | It works, but it needed: turning off two Block Public Access settings on the bucket, a bucket policy for `s3:GetObject`, setting `application/manifest+json` for the `.webmanifest` file by hand, and using `/index.html` as the start address, because the bucket's root returns an XML "AccessDenied". | All scripted in `server/dock_server/webapp.py`. | A one-step "host a static web app" option with HTTPS, or a sample for PWAs. |

## What worked well
- Bedrock's Converse API: one call style for every model, so switching between Nova and Claude was a one-line change.
- Tool use with `toolChoice: any` and temperature 0 gave steady tool picks.
- S3 + a small `address.json` gave us a stable app link with a changing tunnel behind it, for pennies.
