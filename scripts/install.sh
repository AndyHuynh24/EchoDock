#!/bin/bash
# One-time setup for Dock on a Mac. Safe to run again.
#   git clone <repo> && cd OneDock && ./scripts/install.sh
# Then open Dock with OneDock.app.

set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.onedock.dock"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

step() { printf "\n\033[1m%s\033[0m\n" "$1"; }

if [ "$(uname)" != "Darwin" ]; then
  echo "Dock's desktop agent needs macOS for now."
  exit 1
fi

step "1/5  Tools"
if ! command -v uv >/dev/null; then
  echo "Installing uv (runs Dock's Python code)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v cloudflared >/dev/null; then
  if command -v brew >/dev/null; then
    echo "Installing cloudflared (gives the phone a secure address)..."
    brew install cloudflared
  else
    echo "Please install Homebrew from https://brew.sh, then run this again."
    exit 1
  fi
fi
echo "uv and cloudflared are ready."

step "2/5  Dock's Python packages"
(cd server && uv sync -q)
(cd agent && uv sync -q)
echo "Installed."

step "3/5  Your private token"
[ -f .dock-token ] || (umask 077 && openssl rand -hex 16 > .dock-token)
echo "Saved in .dock-token (keep it secret: it is the password for your phone link)."

step "4/5  Amazon Bedrock (the AI)"
if command -v aws >/dev/null && aws sts get-caller-identity >/dev/null 2>&1; then
  echo "AWS login found."
else
  echo "No AWS login found yet. Install the AWS CLI (brew install awscli), run 'aws login',"
  echo "and use region us-east-1. The setup page turns green when it works."
fi

step "5/5  OneDock.app"
./scripts/build_app.sh
read -r -p "Start Dock automatically when you log in? [Y/n] " answer
if [[ ! "$answer" =~ ^[Nn] ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF2
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>$ROOT/OneDock.app</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF2
  echo "Dock will start by itself when you log in. (Change it any time from the face in the menu bar.)"
fi
echo "Opening Dock. Follow the welcome window; after that, Dock lives in the menu bar."
open "$ROOT/OneDock.app"
