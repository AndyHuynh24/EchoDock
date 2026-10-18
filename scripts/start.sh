#!/bin/bash
# Starts Dock: the server (which also opens the secure phone address) and the
# desktop agent. Press Ctrl+C to stop both.
# Setup page with the phone QR code: http://localhost:8000/setup

set -e
cd "$(dirname "$0")/.."
# Also find tools when started at login, where PATH is minimal.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Already running (e.g. OneDock.app opened again)? Just show its window.
if curl -s -m 1 -o /dev/null http://localhost:8000/style.css; then
  curl -s -m 3 -X POST http://localhost:8000/setup/show-window >/dev/null || true
  echo "Dock is already running."
  exit 0
fi

[ -f .dock-token ] || (umask 077 && openssl rand -hex 16 > .dock-token)
export DOCK_TOKEN="${DOCK_TOKEN:-$(cat .dock-token)}"

trap 'kill 0' EXIT

# "uv sync" installs anything missing; then Python runs directly (no extra
# launcher process left in memory).
(cd server && uv sync -q && exec .venv/bin/python -u -m dock_server.main) &
sleep 3
(cd agent && uv sync -q && exec .venv/bin/python -u -m dock_agent.main) &

echo "Dock is running. Setup page: http://localhost:8000/setup"
wait
