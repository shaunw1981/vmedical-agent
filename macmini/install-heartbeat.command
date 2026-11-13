#!/usr/bin/env bash
#
# install-heartbeat.command — DOUBLE-CLICK once to schedule the uptime heartbeat.
# It runs macmini/heartbeat.sh every 2 minutes so Healthchecks.io knows the Mac
# and dashboard are alive. (First time, if macOS blocks it: right-click → Open.)
#
# Prerequisite: set HEALTHCHECK_PING_URL in your .env first (see heartbeat.sh).

set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.vmedical-agent.heartbeat"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
SCRIPT="$APP_DIR/macmini/heartbeat.sh"

chmod +x "$SCRIPT" 2>/dev/null || true

if ! grep -qE '^HEALTHCHECK_PING_URL=.+' "$APP_DIR/.env" 2>/dev/null; then
    echo "⚠️  HEALTHCHECK_PING_URL isn't set in your .env yet."
    echo "    1) Create a check at https://healthchecks.io (free) and copy its ping URL."
    echo "    2) Add this line to your .env:  HEALTHCHECK_PING_URL=https://hc-ping.com/your-uuid"
    echo "    3) Run this installer again."
    [ -t 0 ] && read -r -p "Press Return to close." _ || true
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SCRIPT}</string>
  </array>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>/tmp/vmedical-heartbeat.err</string>
</dict>
</plist>
PLIST

# Load into the per-user GUI domain so it persists after an SSH session ends
# (a plain `launchctl load` over SSH would die with the session). Falls back to
# the legacy load if bootstrap isn't available.
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
if ! launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST" 2>/dev/null || true
fi
launchctl kickstart "${DOMAIN}/${LABEL}" 2>/dev/null || true

echo "✅ Heartbeat scheduled — it will ping every 2 minutes starting now."
echo "   Check your Healthchecks.io dashboard; it should show a ping within a minute."
[ -t 0 ] && read -r -p "Press Return to close." _ || true
