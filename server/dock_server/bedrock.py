"""Small helpers around the Amazon Bedrock Converse API.

Understanding what the user said (picking the tool) uses DOCK_ROUTER_MODEL
(default: Claude Haiku 4.5: in our routing test it understood vague requests
better than Nova 2 Lite and asked when it wasn't sure, instead of guessing).
Dock's instructions and tool list are the same for every request, so they're
cached (prompt caching): that makes Haiku about as cheap as Nova 2 Lite.
Small one-off jobs (summaries, matching a menu item) use DOCK_MODEL (default:
Amazon Nova 2 Lite; the older, cheaper Nova Lite made up file paths and skipped
steps). Jobs that need more judgment, like tidy-up plans, use DOCK_SMART_MODEL
(default: Claude Haiku 4.5).
AWS credentials and region come from the usual AWS settings (aws login /
AWS_REGION). These functions block, so call them with asyncio.to_thread.
"""

import os
import re

import boto3
from botocore.config import Config

MODEL_ID = os.environ.get("DOCK_MODEL", "us.amazon.nova-2-lite-v1:0")
# A stronger, pricier model for the few jobs that need careful judgment, like tidy plans.
# Haiku 4.5 takes about 10 s for a tidy plan. Sonnet 4.6 (us.anthropic.claude-sonnet-4-6)
# makes slightly better plans but takes about 30 s.
SMART_MODEL_ID = os.environ.get("DOCK_SMART_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
# Picks the tool for each request (voice.py). Set it to MODEL_ID's Nova 2 Lite to save
# a little more: it's about 0.15 s faster but guesses when a request is vague.
ROUTER_MODEL_ID = os.environ.get("DOCK_ROUTER_MODEL", SMART_MODEL_ID)

_client = boto3.client(
    "bedrock-runtime",
    config=Config(read_timeout=20, retries={"total_max_attempts": 2, "mode": "standard"}),
)


def converse(messages: list[dict], system: str, tools: list[dict] | None = None, max_tokens: int = 300,
             must_use_tool: bool = False, model: str = MODEL_ID, extra_system: str = "") -> dict:
    """extra_system: instructions that change between requests (the app in front,
    the time). They go after `system` and the tools, which are cached for
    Claude models: a repeat request then pays a tenth of the price for them."""
    cache = "anthropic" in model
    blocks = [{"text": system}] + ([{"cachePoint": {"type": "default"}}] if cache else [])
    kwargs = {
        "modelId": model,
        "messages": messages,
        "system": blocks + ([{"text": extra_system}] if extra_system else []),
        # Temperature 0 makes tool picking steady (same request, same tool).
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
    }
    if tools:
        kwargs["toolConfig"] = {"tools": tools + ([{"cachePoint": {"type": "default"}}] if cache else [])}
        if must_use_tool:
            kwargs["toolConfig"]["toolChoice"] = {"any": {}}
    return _client.converse(**kwargs)


def message_text(message: dict) -> str:
    text = "".join(block.get("text", "") for block in message["content"])
    # Nova sometimes writes its reasoning in <thinking> tags; that must never be spoken.
    return re.sub(r"<thinking>.*?(</thinking>|$)", "", text, flags=re.DOTALL).strip()


def ask_web(prompt: str, system: str, max_tokens: int = 300) -> tuple[str, list[str]]:
    """Like ask, but Nova may search the web first (Bedrock's built-in "web
    grounding"). Costs about $0.03 per search, so Dock only uses it when an
    app's own menus don't have the answer. Returns the answer and its source
    web addresses."""
    response = _client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        system=[{"text": system}],
        toolConfig={"tools": [{"systemTool": {"name": "nova_grounding"}}]},
        inferenceConfig={"maxTokens": max_tokens},
    )
    content = response["output"]["message"]["content"]
    sources = [c["location"]["web"]["url"] for block in content if "citationsContent" in block
               for c in block["citationsContent"]["citations"] if "web" in c.get("location", {})]
    return message_text({"content": [b for b in content if "text" in b]}), list(dict.fromkeys(sources))


def ask(prompt: str, system: str, max_tokens: int = 50, model: str = MODEL_ID) -> str:
    """One question, one short text answer."""
    response = converse([{"role": "user", "content": [{"text": prompt}]}], system, max_tokens=max_tokens, model=model)
    return message_text(response["output"]["message"])
