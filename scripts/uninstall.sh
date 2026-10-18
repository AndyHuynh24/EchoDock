#!/bin/bash
# Stops Dock from starting at login. Your workspaces, notes and activity
# (in ~/.dock and server/.data) are kept; delete those folders to remove them too.

LABEL="com.onedock.dock"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Stopped Dock." || echo "Dock wasn't running at login."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Dock will no longer start at login."
