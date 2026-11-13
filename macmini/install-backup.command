#!/usr/bin/env bash
#
# install-backup.command — schedule the nightly encrypted backup (runs daily at
# 2:30am via macmini/backup.sh). Can be double-clicked, or run over SSH.
#
# Prerequisites (set up first):
#   1. Install restic:              brew install restic
#   2. In .env, set an encryption key and at least one destination:
#        RESTIC_PASSWORD=<a long random passphrase — KEEP A COPY OFFSITE>
#        BACKUP_LOCAL_REPO=/Volumes/<YourDrive>/vmedical-restic   (external drive), and/or
#        BACKUP_B2_REPO=b2:<bucket>:vmedical + B2_ACCOUNT_ID=... + B2_ACCOUNT_KEY=...

set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"
LABEL="com.vmedical-agent.backup"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
SCRIPT="$APP_DIR/macmini/backup.sh"
chmod +x "$SCRIPT" 2>/dev/null || true

getenv(){ grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'\' | xargs; }

problem=0
if ! command -v restic >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/restic ]; then
  echo "⚠️  restic isn't installed. Run:  brew install restic"; problem=1; fi
if ! grep -qE '^RESTIC_PASSWORD=.+' "$ENV_FILE" 2>/dev/null; then
  echo "⚠️  RESTIC_PASSWORD isn't set in .env (the encryption key)."; problem=1; fi
if ! grep -qE '^BACKUP_LOCAL_REPO=.+' "$ENV_FILE" 2>/dev/null && ! grep -qE '^BACKUP_B2_REPO=.+' "$ENV_FILE" 2>/dev/null; then
  echo "⚠️  No destination set — add BACKUP_LOCAL_REPO and/or BACKUP_B2_REPO to .env."; problem=1; fi
if [ "$problem" -eq 1 ]; then
  echo ""; echo "Fix the above (see the notes at the top of this file), then run this again."
  [ -t 0 ] && read -r -p "Press Return to close." _ || true
  exit 1
fi

echo "Running a first backup now to verify it works (this can take a while the first time)..."
if bash "$SCRIPT"; then echo "✅ First backup succeeded."; else
  echo "❌ The first backup failed — see $APP_DIR/data/backup.log. Not scheduling until it works."
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
  <array><string>/bin/bash</string><string>${SCRIPT}</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardErrorPath</key><string>${APP_DIR}/data/backup.log</string>
</dict>
</plist>
PLIST

# Load into the GUI domain so it survives an SSH session ending.
UID_NUM="$(id -u)"; DOMAIN="gui/${UID_NUM}"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
if ! launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST" 2>/dev/null || true
fi

echo "✅ Nightly encrypted backup scheduled for 2:30am."
echo "   To restore later:  export RESTIC_PASSWORD=...; restic -r <repo> snapshots   then   restic -r <repo> restore latest --target /tmp/restore"
[ -t 0 ] && read -r -p "Press Return to close." _ || true
