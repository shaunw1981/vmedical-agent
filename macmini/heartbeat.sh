#!/usr/bin/env bash
#
# heartbeat.sh — "dead-man's switch". Every couple of minutes this checks the
# dashboard's own /health and then pings an external service (Healthchecks.io).
# If this Mac loses power or internet, the pings stop and that service alerts
# you — catching the one case an on-Mac check never can: the Mac being down.
#
# Set HEALTHCHECK_PING_URL in your .env to your Healthchecks.io ping URL, e.g.
#   HEALTHCHECK_PING_URL=https://hc-ping.com/your-uuid-here
# Then double-click macmini/install-heartbeat.command once to schedule it.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"

PING_URL=""
if [ -f "$ENV_FILE" ]; then
    PING_URL="$(grep -E '^HEALTHCHECK_PING_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'\' | xargs)"
fi
[ -z "${PING_URL:-}" ] && PING_URL="${HEALTHCHECK_PING_URL:-}"
[ -z "${PING_URL:-}" ] && exit 0   # not configured — nothing to do

# Healthy → ping success; unhealthy/unreachable → ping the /fail endpoint so the
# alert fires immediately instead of waiting for the grace period to lapse.
if curl -fsS --max-time 10 http://localhost:8000/health >/dev/null 2>&1; then
    curl -fsS --max-time 10 "$PING_URL" >/dev/null 2>&1 || true
else
    curl -fsS --max-time 10 "${PING_URL%/}/fail" >/dev/null 2>&1 || true
fi
