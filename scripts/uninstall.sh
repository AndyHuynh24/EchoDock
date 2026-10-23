#!/bin/bash
# Stops Dock from starting at login. Data in ~/.dock and server/.data is kept.

LABEL="com.onedock.dock"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Stopped Dock." || echo "Dock wasn't running at login."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Dock will no longer start at login."
