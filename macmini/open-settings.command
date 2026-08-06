#!/usr/bin/env bash
#
# open-settings.command — DOUBLE-CLICK to open the settings file (.env) in
# TextEdit. (First time, if macOS blocks it: right-click -> Open -> Open.)

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
open -e "$APP_DIR/.env"
