# Friction log: building Dock (Alexa+ track)

What we tried with Amazon's tools, what we expected, what actually happened, and what would fix it. Every entry happened while building Dock.

**Severity:** **Critical** = blocked the planned path · **High** = cost hours or broke a feature · **Medium** = needed a workaround · **Low** = an annoyance.

---

## 1. Bedrock: Titan embeddings throttled while indexing, quietly losing data
- **Severity:** High
- **Task:** index a real Mac's documents and email for "ask about your stuff" (RAG): about 2,200 chunks with Titan Text Embeddings v2.
- **Steps:** called `InvokeModel` on `amazon.titan-embed-text-v2:0` from 8 threads with boto3's default retry settings.
- **Expected:** a few minutes of indexing, with slower calls if we went over the limit.
- **Actual:** 801 calls failed with `ThrottlingException: Too many requests, please wait before trying again`. Only 1,391 chunks were stored, about 4,500 tokens instead of the ~500,000 expected. The default retries gave up quickly, and the error doesn't say what the limit is.
- **Workaround:** a separate boto3 client for embeddings with `retries={"total_max_attempts": 10, "mode": "adaptive"}`, 4 threads instead of 8, and any item with a failed chunk marked so the next refresh tries it again. The full index then built in about 6 minutes, with nothing lost.
- **Suggestion:** put the default embedding quota (requests per minute) on the model card and in the error message, and offer a batch embedding call for many short texts, so builders don't need dozens of parallel requests.

## 2. Bedrock: newer models refused for our account
- **Severity:** Medium
- **Task:** compare newer Claude models for tool picking.
- **Steps:** `Converse` with newer Claude model IDs in `us-east-1`.
- **Expected:** an error that says how to get access, or the model working.
- **Actual:** `AccessDeniedException: anthropic.claude-haiku-5-5 is not available for this account. … contact AWS Sales`. Sonnet 5.5 gave the same error. There's no list of which models an account can call, so we found out one model at a time.
- **Workaround:** stayed on Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`), which our eval shows is enough: 130 of 130 test phrases pick the right tool.
- **Suggestion:** a "models this account can use" list in the console and API, and a self-serve way to request a model, instead of "contact AWS Sales."

## 3. Nova 2 Lite: the inference profile ID and `<thinking>` text
- **Severity:** Medium
- **Task:** use Amazon Nova 2 Lite for small jobs and tool calling.
- **Steps:** `Converse` with the model ID from the model card.
- **Expected:** the base model ID works, and the reply is only the answer.
- **Actual:** it has to be called through the inference profile ID (`us.amazon.nova-2-lite-v1:0`). It sometimes puts `<thinking>…</thinking>` in the text reply, which a voice assistant must never read out.
- **Workaround:** the `us.` profile ID, and we strip `<thinking>` blocks before speaking.
- **Suggestion:** show the profile ID first on the model card, and add an option to never return thinking text.

## 4. Nova web grounding: price hard to find, awkward response shape
- **Severity:** Low
- **Task:** answer "how do I translate a page in Chrome?" from the web, with a source.
- **Steps:** `Converse` with the `nova_grounding` system tool.
- **Expected:** a price on the Bedrock pricing page, and an answer plus a list of sources.
- **Actual:** it worked nicely (3–5 s, and it cited Google's own help page). But we couldn't find the price on the official pricing page, only about $0.03 per request on a third-party site. The answer comes back as many small `citationsContent` blocks between text blocks, and the search result itself shows as "[HIDDEN]".
- **Workaround:** joined the text blocks and kept the first source's site. Turned the feature off by default (`DOCK_WEB_SEARCH=on` enables it) because of the cost.
- **Suggestion:** put the grounding price next to the model prices, and return a simple "answer + sources" shape.

## 5. Prompt caching: great, but the 5-minute cache is short for a voice assistant
- **Severity:** Low
- **Task:** cut the cost of the tool picker, which sends ~7,600 tokens of tools and instructions every request.
- **Steps:** one `cachePoint` after the tools and one after the fixed instructions in `Converse`.
- **Expected:** most of the prompt read from the cache.
- **Actual:** it worked: about 91% of prompt tokens came from the cache, and Claude Haiku 4.5 became cheaper per request (~$0.0018) than Nova 2 Lite without caching. But the cache lasts only 5 minutes, and a desk assistant is used every 10–20 minutes, so the first request after a pause costs several times more.
- **Workaround:** the request's changing facts (the app in front, the time) go in a system block after the cache point, so the cached part never changes.
- **Suggestion:** a longer cache time option for apps that are used now and then.

## 6. Amazon S3: hosting a small installable web app took many steps
- **Severity:** Medium
- **Task:** host the phone web app (a PWA) at a fixed HTTPS address, so its link never changes while the tunnel behind it does.
- **Steps:** created a bucket and uploaded the files with boto3.
- **Expected:** a public HTTPS page.
- **Actual:** it works, but it needed: turning off two Block Public Access settings, a bucket policy for `s3:GetObject`, setting `application/manifest+json` on the `.webmanifest` by hand, and using `/index.html` as the start address, because the bucket's root returns an XML "AccessDenied".
- **Workaround:** all of it is scripted in `server/dock_server/webapp.py`.
- **Suggestion:** a one-step "host a static web app over HTTPS" option, or a sample for PWAs.

---

## What worked well
- **Bedrock's Converse API:** one call style for every model, so switching between Nova and Claude was a one-line change, and tool use with `toolChoice: any` at temperature 0 gave steady picks.
- **Prompt caching** was two lines of code and cut the cost of every request.
- **Titan Text Embeddings v2** at 512 dimensions: about $0.01 to index a whole Mac's documents and email, and accurate enough that our search eval gets 22 of 22 answers right.
- **S3 plus a small `address.json`** gave us a stable app link with a changing tunnel behind it, for pennies.
