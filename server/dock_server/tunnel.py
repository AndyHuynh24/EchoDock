"""Public HTTPS address via a Cloudflare quick tunnel, restarted if it stops responding.

Set DOCK_PUBLIC_URL to use your own address instead.
"""

import atexit
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

_public_url = os.environ.get("DOCK_PUBLIC_URL", "").rstrip("/")
_problem = ""
_process: subprocess.Popen | None = None
CHECK_EVERY = 30
FAILS_BEFORE_RESTART = 3


def public_url() -> str:
    return _public_url


def problem() -> str:
    return _problem


def start(port: int) -> None:
    global _problem
    if _public_url:
        return
    if not shutil.which("cloudflared"):
        _problem = ("cloudflared isn't installed. Run: winget install Cloudflare.cloudflared" if sys.platform == "win32"
                    else "cloudflared isn't installed. Run: brew install cloudflared")
        return
    atexit.register(_stop)
    _open(port)
    threading.Thread(target=_watch, args=(port,), daemon=True).start()


def _open(port: int) -> None:
    global _process
    _process = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    threading.Thread(target=_read_address, args=(_process,), daemon=True).start()


def _stop() -> None:
    if _process:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()


def _read_address(process: subprocess.Popen) -> None:
    global _public_url
    for line in process.stderr:
        found = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if found and not _public_url and process is _process:
            _public_url = found.group()
            print(f"Phone address: {_public_url}")


def _works(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/style.css", timeout=10) as response:
            return response.status == 200
    except Exception:
        return False


def _watch(port: int) -> None:
    """Restart the tunnel when the address stops working."""
    global _public_url
    fails = 0
    while True:
        time.sleep(CHECK_EVERY)
        url = _public_url
        if not url:
            continue
        fails = 0 if _works(url) else fails + 1
        if fails >= FAILS_BEFORE_RESTART:
            print(f"Phone address {url} stopped working. Starting a new one (the installed phone app follows it by itself).")
            fails = 0
            _public_url = ""
            _stop()
            _open(port)
