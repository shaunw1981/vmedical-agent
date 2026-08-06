#!/usr/bin/env bash
#
# start.sh — starts the notes app. The Mac Mini runs this automatically in the
# background (see install.command). You normally never run it by hand.
#
# "caffeinate -i" keeps the Mac from going to sleep while the app is running,
# so it stays available 24/7 without you changing any system settings.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # the project folder

exec caffeinate -i .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
