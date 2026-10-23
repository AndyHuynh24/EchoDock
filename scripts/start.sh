#!/bin/bash
# Starts the Dock server and desktop agent. Ctrl+C stops both.
# Setup page: http://localhost:8000/setup

set -e
cd "$(dirname "$0")/.."
# PATH is minimal when started at login.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Already running: just show the window.
if curl -s -m 1 -o /dev/null http://localhost:8000/style.css; then
  curl -s -m 3 -X POST http://localhost:8000/setup/show-window >/dev/null || true
  echo "Dock is already running."
  exit 0
fi

[ -f .dock-token ] || (umask 077 && openssl rand -hex 16 > .dock-token)
export DOCK_TOKEN="${DOCK_TOKEN:-$(cat .dock-token)}"
# Optional: a Gmail label to read instead of the inbox (e.g. echo Test > .dock-mail-folder).
[ -f .dock-mail-folder ] && export DOCK_MAIL_FOLDER="$(cat .dock-mail-folder)"

trap 'kill 0' EXIT

# Install anything missing, then run Python directly.
(cd server && uv sync -q && exec .venv/bin/python -u -m dock_server.main) &
sleep 3
(cd agent && uv sync -q && exec .venv/bin/python -u -m dock_agent.main) &

echo "Dock is running. Setup page: http://localhost:8000/setup"
wait
