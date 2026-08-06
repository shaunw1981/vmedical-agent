#!/usr/bin/env bash
#
# restart.command — DOUBLE-CLICK to restart the dashboard after you change
# settings. (First time, if macOS blocks it: right-click -> Open -> Open.)

PLIST="$HOME/Library/LaunchAgents/com.vmedical-agent.plist"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST" 2>/dev/null || true
echo "Restarted. Wait about 10 seconds, then refresh the dashboard in your browser."
read -r -p "Press Return to close this window." _
