#!/usr/bin/env bash
#
# update.command — DOUBLE-CLICK to get the latest version of the dashboard.
#
# It downloads the newest code from GitHub and restarts the app for you.
# Your settings (.env) and your data are NEVER touched.
#
# First time you double-click, if macOS blocks it:
#   right-click the file -> Open -> Open. You only do that once.

set -euo pipefail

# Where the project lives (the folder this file's "macmini" folder sits in).
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

LABEL="com.vmedical-agent"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
REPO_ZIP="https://github.com/shaunw1981/vmedical-agent/archive/refs/heads/main.zip"

echo "============================================================"
echo " Updating the Spa Dashboard to the latest version"
echo "============================================================"
echo ""

# Work in a throwaway folder that cleans itself up.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. Download the newest code from GitHub.
echo "==> Downloading the latest version..."
if ! curl -fsSL "$REPO_ZIP" -o "$TMP/latest.zip"; then
    echo ""
    echo "!! Couldn't download the update. Check the Mac's internet connection"
    echo "   and try again. (Nothing was changed.)"
    read -r -p "Press Return to close this window." _
    exit 1
fi

# 2. Unzip it.
echo "==> Unpacking..."
unzip -q "$TMP/latest.zip" -d "$TMP"
SRC="$TMP/vmedical-agent-main"

if [ ! -d "$SRC" ]; then
    echo "!! The download didn't look right. Nothing was changed. Please try again."
    read -r -p "Press Return to close this window." _
    exit 1
fi

# 3. Copy the new code over the app — but protect your settings and data.
#    --delete keeps the folder a clean mirror of GitHub, while the excludes
#    make sure your .env (settings), data (database + notes), the Python
#    environment, and git history are left exactly as they are.
echo "==> Applying the update (your settings and data are left untouched)..."
rsync -a --delete \
    --exclude='.env' \
    --exclude='data/' \
    --exclude='.venv/' \
    --exclude='.git/' \
    "$SRC"/ "$APP_DIR"/

# 4. Update the app's components in case anything new is needed.
if [ -x "$APP_DIR/.venv/bin/pip" ]; then
    echo "==> Updating components..."
    "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" || true
fi

# 5. Clear macOS download flags and make the helper files runnable again.
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true
chmod +x "$APP_DIR"/macmini/*.command "$APP_DIR"/macmini/start.sh 2>/dev/null || true

# 6. Restart the dashboard so the new version goes live.
echo "==> Restarting the dashboard..."
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST" 2>/dev/null || true

echo ""
echo "============================================================"
echo " Done! You're on the latest version."
echo ""
echo " Wait about 10 seconds, then refresh the dashboard in your"
echo " browser with  Cmd + Shift + R  (a hard refresh)."
echo "============================================================"
read -r -p "Press Return to close this window." _
