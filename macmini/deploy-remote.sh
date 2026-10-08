#!/usr/bin/env bash
#
# deploy-remote.sh — HEADLESS deploy, meant to be run OVER SSH from your office.
#
# It does the same job as double-clicking update.command (download the latest
# code from GitHub, apply it while protecting .env + data + the Python env,
# then restart the dashboard) — but with three differences that matter when
# you are NOT sitting at the Mac:
#
#   1. It never pauses for "Press Return" — it just runs and exits.
#   2. It restarts the app in the Mac's GUI launchd domain (gui/<uid>), which
#      is the only way a restart triggered over SSH actually takes effect.
#   3. It prints a clear OK / FAILED result and a health check at the end,
#      and exits non-zero on failure so you can tell from your terminal.
#
# Typical use from your office machine (Tailscale + Remote Login set up):
#   ssh agent@valley-macmini 'bash ~/vmedical-agent/macmini/deploy-remote.sh'
#
# First-time bootstrap (before the file exists on the Mac), run over SSH:
#   curl -fsSL https://raw.githubusercontent.com/shaunw1981/vmedical-agent/main/macmini/deploy-remote.sh | bash
#
# Your settings (.env), database, and Obsidian vault are NEVER touched.

set -euo pipefail

LABEL="com.vmedical-agent"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
REPO_ZIP="https://github.com/shaunw1981/vmedical-agent/archive/refs/heads/main.zip"

log(){ echo "[deploy] $*"; }
die(){ echo "[deploy] ERROR: $*" >&2; exit 1; }

# --- Find the app folder, whether this runs on-disk or piped from curl -------
APP_DIR=""
if [ -n "${VMEDICAL_DIR:-}" ] && [ -f "${VMEDICAL_DIR}/app.py" ]; then
    APP_DIR="$VMEDICAL_DIR"
elif [ -n "${BASH_SOURCE:-}" ] && [ "${BASH_SOURCE[0]:-}" != "bash" ] && [ -f "${BASH_SOURCE[0]:-/nonexistent}" ]; then
    CAND="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd || true)"
    [ -n "$CAND" ] && [ -f "$CAND/app.py" ] && APP_DIR="$CAND"
fi
if [ -z "$APP_DIR" ] && [ -f "$HOME/vmedical-agent/app.py" ]; then
    APP_DIR="$HOME/vmedical-agent"
fi
if [ -z "$APP_DIR" ]; then
    APP_DIR="$(find "$HOME" -maxdepth 4 -name app.py -path '*vmedical*' 2>/dev/null | head -1 | xargs -I{} dirname {} 2>/dev/null || true)"
fi
[ -n "$APP_DIR" ] && [ -d "$APP_DIR" ] || die "Could not locate the vmedical-agent folder under \$HOME."
cd "$APP_DIR"
log "App folder: $APP_DIR"

# --- Download + unpack the latest code --------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

log "Downloading latest code from GitHub..."
curl -fsSL "$REPO_ZIP" -o "$TMP/latest.zip" || die "Download failed (check the Mac's internet). Nothing changed."

log "Unpacking..."
unzip -q "$TMP/latest.zip" -d "$TMP"
SRC="$TMP/vmedical-agent-main"
[ -d "$SRC" ] || die "Downloaded archive looked wrong. Nothing changed."

# --- Apply, protecting settings + data --------------------------------------
log "Applying update (.env, data/, .venv/, .git/ are left untouched)..."
rsync -a --delete \
    --exclude='.env' \
    --exclude='data/' \
    --exclude='.venv/' \
    --exclude='.git/' \
    "$SRC"/ "$APP_DIR"/

if [ -x "$APP_DIR/.venv/bin/pip" ]; then
    log "Updating Python components..."
    "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" || log "WARN: pip install reported a problem (continuing)."
fi

xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true
chmod +x "$APP_DIR"/macmini/*.command "$APP_DIR"/macmini/*.sh 2>/dev/null || true

# --- Restart in the GUI launchd domain (works over SSH) ---------------------
log "Restarting the dashboard..."
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"
if [ -f "$PLIST" ]; then
    launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || true   # no-op if already loaded
    launchctl enable "${DOMAIN}/${LABEL}" 2>/dev/null || true
    if ! launchctl kickstart -k "${DOMAIN}/${LABEL}" 2>/dev/null; then
        log "kickstart unavailable; falling back to unload/load."
        launchctl unload "$PLIST" 2>/dev/null || true
        launchctl load  "$PLIST" 2>/dev/null || true
    fi
else
    die "Launch agent not found at $PLIST — run macmini/install.command once on the Mac first."
fi

# --- Health check ------------------------------------------------------------
log "Waiting for the app to come back up..."
HEALTH=""
for _ in $(seq 1 20); do
    HEALTH="$(curl -s --max-time 2 http://localhost:8000/health 2>/dev/null || true)"
    [ -n "$HEALTH" ] && break
    sleep 1
done

echo "------------------------------------------------------------"
if echo "$HEALTH" | grep -q '"status"'; then
    log "OK — dashboard is live on the latest version."
    log "Health: $HEALTH"
    echo "------------------------------------------------------------"
    exit 0
else
    log "FAILED — app did not respond on http://localhost:8000/health after restart."
    log "Check the logs on the Mac, or try again."
    echo "------------------------------------------------------------"
    exit 1
fi
