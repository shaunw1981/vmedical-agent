#!/usr/bin/env bash
#
# install.command — DOUBLE-CLICK THIS FILE on the Mac Mini to set everything up.
#
# It will:
#   1. Build an isolated Python environment and install what the app needs.
#   2. Create your settings file (.env) if you don't have one yet.
#   3. Set the app to start automatically and stay running in the background.
#
# If macOS says it "cannot be opened because it is from an unidentified
# developer", right-click the file -> Open -> Open. You only do that once.

set -euo pipefail

# Figure out where this project lives (the folder this file is in, one up).
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
LABEL="com.vmedical-agent"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo "==> Project folder: $APP_DIR"

# 0. Remove the internet "quarantine" flag from the project files, so macOS
#    lets the background service run start.sh (otherwise you get an
#    "Operation not permitted" error and the app never starts).
echo "==> Clearing download security flags..."
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true

# 1. Check Python is installed.
if ! command -v python3 >/dev/null 2>&1; then
    echo "!! Python 3 is not installed."
    echo "   Please install it first from https://www.python.org/downloads/"
    echo "   (download the macOS installer, run it, then double-click this again)."
    read -r -p "Press Return to close." _
    exit 1
fi

# 2. Build the environment and install dependencies.
echo "==> Setting up Python environment (one minute or so)..."
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

# 3. Create the settings file if it's missing.
if [ ! -f .env ]; then
    cp .env.example .env
    # Auto-generate a strong SESSION_SECRET so you never have to.
    SECRET="$(./.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
    ./.venv/bin/python - "$APP_DIR/.env" "$SECRET" <<'PY'
import re, sys
path, secret = sys.argv[1], sys.argv[2]
text = open(path).read()
text = re.sub(r'(?m)^SESSION_SECRET=.*$', 'SESSION_SECRET=' + secret, text)
open(path, 'w').write(text)
PY
    echo "==> Created a settings file (.env) with a secure key already filled in."
fi

# 4. Make the helper scripts runnable.
chmod +x macmini/start.sh macmini/restart.command macmini/open-settings.command macmini/update.command 2>/dev/null || true

# 5. Install the background service (a macOS "LaunchAgent").
echo "==> Setting the app to run automatically..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${APP_DIR}/macmini/start.sh</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>${APP_DIR}/data/app.log</string>
    <key>StandardErrorPath</key><string>${APP_DIR}/data/app.log</string>
</dict>
</plist>
PLIST_EOF

mkdir -p "$APP_DIR/data"

# (Re)load the service.
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "============================================================"
echo " Done! The notes app is installed and running."
echo ""
echo " View the notes page:   open http://localhost:8000"
echo " Edit settings:         open -e \"$APP_DIR/.env\""
echo " After editing .env:    launchctl unload \"$PLIST\" && launchctl load \"$PLIST\""
echo "============================================================"
read -r -p "Press Return to close this window." _
