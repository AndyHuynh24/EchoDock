"""Helpers around the Amazon Bedrock Converse API.

These calls block; run them with asyncio.to_thread.
"""

import json
import os
import re
import time

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from dock_server import tracing

MODEL_ID = os.environ.get("DOCK_MODEL", "us.amazon.nova-2-lite-v1:0")
# Used for jobs that need more judgment, like tidy-up plans.
SMART_MODEL_ID = os.environ.get("DOCK_SMART_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
# Picks the tool for each request (voice.py).
ROUTER_MODEL_ID = os.environ.get("DOCK_ROUTER_MODEL", SMART_MODEL_ID)
# Embeddings for search_my_stuff (library.py).
EMBED_MODEL_ID = os.environ.get("DOCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
EMBED_DIMENSIONS = 512

_client = boto3.client(
    "bedrock-runtime",
    # Retry short Bedrock outages.
    config=Config(read_timeout=20, retries={"total_max_attempts": 4, "mode": "standard"}),
)


def converse(messages: list[dict], system: str, tools: list[dict] | None = None, max_tokens: int = 300,
             must_use_tool: bool = False, model: str = MODEL_ID, extra_system: str = "", purpose: str = "tool") -> dict:
    """extra_system: per-request instructions, placed after the cached system prompt and tools.
    purpose: label for the trace.
    """
    cache = "anthropic" in model
    blocks = [{"text": system}] + ([{"cachePoint": {"type": "default"}}] if cache else [])
    kwargs = {
        "modelId": model,
        "messages": messages,
        "system": blocks + ([{"text": extra_system}] if extra_system else []),
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
    }
    if tools:
        kwargs["toolConfig"] = {"tools": tools + ([{"cachePoint": {"type": "default"}}] if cache else [])}
        if must_use_tool:
            kwargs["toolConfig"]["toolChoice"] = {"any": {}}
    return _timed(purpose, model, kwargs)


# If a US model is busy, retry once through the global route.
BUSY = ("ServiceUnavailableException", "ThrottlingException", "ModelNotReadyException", "InternalServerException")


def _timed(purpose: str, model: str, kwargs: dict) -> dict:
    """Call Bedrock and add the call (time, tokens, cost) to the request's trace."""
    started = time.perf_counter()
    try:
        response = _client.converse(**kwargs)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") not in BUSY or not kwargs["modelId"].startswith("us."):
            raise
        print(f"Bedrock is busy ({e.response['Error']['Code']}): trying the global route")
        response = _client.converse(**{**kwargs, "modelId": "global." + kwargs["modelId"].removeprefix("us.")})
    tracing.model_step(purpose, model, response, time.perf_counter() - started)
    return response


def message_text(message: dict) -> str:
    text = "".join(block.get("text", "") for block in message["content"])
    # Strip any <thinking> text before it gets spoken.
    return re.sub(r"<thinking>.*?(</thinking>|$)", "", text, flags=re.DOTALL).strip()


def ask_web(prompt: str, system: str, max_tokens: int = 300) -> tuple[str, list[str]]:
    """Like ask(), with Bedrock web grounding. Returns the answer and its sources."""
    response = _timed("web search", MODEL_ID, {
        "modelId": MODEL_ID,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "system": [{"text": system}],
        "toolConfig": {"tools": [{"systemTool": {"name": "nova_grounding"}}]},
        "inferenceConfig": {"maxTokens": max_tokens},
    })
    content = response["output"]["message"]["content"]
    sources = [c["location"]["web"]["url"] for block in content if "citationsContent" in block
               for c in block["citationsContent"]["citations"] if "web" in c.get("location", {})]
    return message_text({"content": [b for b in content if "text" in b]}), list(dict.fromkeys(sources))


def ask(prompt: str, system: str, max_tokens: int = 50, model: str = MODEL_ID, purpose: str = "tool") -> str:
    """One question, one short text answer."""
    response = converse([{"role": "user", "content": [{"text": prompt}]}], system, max_tokens=max_tokens, model=model,
                        purpose=purpose)
    return message_text(response["output"]["message"])

# Indexing makes many embedding calls in a row, so retry with backoff.
_embed_client = boto3.client(
    "bedrock-runtime",
    config=Config(read_timeout=20, retries={"total_max_attempts": 10, "mode": "adaptive"}),
)


def embed(text: str, trace: bool = True) -> list[float]:
    """Normalized embedding for a piece of text."""
    started = time.perf_counter()
    response = _embed_client.invoke_model(modelId=EMBED_MODEL_ID, body=json.dumps(
        {"inputText": text[:20000], "dimensions": EMBED_DIMENSIONS, "normalize": True}))
    result = json.loads(response["body"].read())
    if trace:
        tracing.model_step("embedding", EMBED_MODEL_ID, {"usage": {"inputTokens": result["inputTextTokenCount"]}},
                           time.perf_counter() - started)
    return result["embedding"]
