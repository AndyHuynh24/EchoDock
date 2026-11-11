"""Smoke test for a running Dock server (local, port-forwarded, or in CI).

    python deploy/smoke_test.py --url http://localhost:8000 --token "$DOCK_TOKEN"

Checks:
  1. GET /healthz returns 200 (skip with --no-healthz for servers without it)
  2. The phone web app is served (GET /style.css)
  3. /mcp refuses a request without the token (401)
  4. /mcp lists the tools when given the token
  5. A WebSocket to /ws/phone connects and receives its first "version" message

Needs only the standard library plus the `websockets` package.
Exits with code 1 if any check fails.
"""

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request

import websockets


def http(method: str, url: str, body: dict | None = None, token: str = "") -> tuple[int, bytes]:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, OSError) as e:  # can't connect at all
        return 0, repr(e).encode()


async def phone_socket(ws_url: str) -> dict:
    async with websockets.connect(ws_url, open_timeout=10) as ws:
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=10))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--no-healthz", action="store_true", help="skip the /healthz check")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        failures += not ok

    if not args.no_healthz:
        status, body = http("GET", f"{base}/healthz")
        # Check the body too: a proxy in front may answer /healthz itself.
        check("GET /healthz is 200", status == 200 and b'"ok":true' in body, f"{status} {body[:80]!r}")

    status, _ = http("GET", f"{base}/style.css")
    check("phone web app is served", status == 200, str(status))

    list_tools = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    status, _ = http("POST", f"{base}/mcp", list_tools)
    check("/mcp without token is 401", status == 401, str(status))

    status, body = http("POST", f"{base}/mcp", list_tools, token=args.token)
    try:
        tools = json.loads(body)["result"]["tools"]
        check("/mcp tools/list with token", status == 200 and len(tools) > 0, f"{len(tools)} tools")
    except (ValueError, KeyError, TypeError):
        check("/mcp tools/list with token", False, f"{status} {body[:200]!r}")

    ws_url = base.replace("http", "ws", 1) + f"/ws/phone?token={args.token}"
    try:
        first = asyncio.run(phone_socket(ws_url))
        check("WebSocket /ws/phone receives 'version'", first.get("kind") == "version", str(first)[:80])
    except Exception as e:
        check("WebSocket /ws/phone receives 'version'", False, repr(e)[:200])

    print("All checks passed." if not failures else f"{failures} check(s) failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
