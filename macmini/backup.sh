#!/usr/bin/env bash
#
# backup.sh — encrypted, automated backup of everything that lives only on this
# Mac: the database + photos + documents (data/), the Obsidian vault (knowledge,
# Charlie's memory, client consult notes), and the .env config.
#
# Uses restic: data is encrypted on THIS Mac before it goes anywhere, so a cloud
# destination only ever stores ciphertext. Backs up to any destination you set
# in .env — a local external drive, an offsite cloud bucket, or both.
#
# Configure in .env (see .env.example):
#   RESTIC_PASSWORD=...            the encryption key — KEEP A COPY OFFSITE
#   BACKUP_LOCAL_REPO=/Volumes/Backup/vmedical-restic     (external drive, optional)
#   BACKUP_B2_REPO=b2:bucket:vmedical    + B2_ACCOUNT_ID / B2_ACCOUNT_KEY  (cloud, optional)
#   BACKUP_HEALTHCHECK_URL=https://hc-ping.com/...        (optional alert, optional)
#
# Schedule it with macmini/install-backup.command.

set -uo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$APP_DIR/.env"
mkdir -p "$APP_DIR/data"
LOG="$APP_DIR/data/backup.log"
STATUS_FILE="$APP_DIR/data/backup-status.txt"

log(){ echo "$(date '+%Y-%m-%dT%H:%M:%S') $*" | tee -a "$LOG" >&2; }
fail(){ echo "$(date '+%Y-%m-%dT%H:%M:%S') FAIL $*" > "$STATUS_FILE"; log "ERROR: $*"; exit 1; }

# Read a single key from .env WITHOUT sourcing it (so a value can't run code).
getenv(){ grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- \
          | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//" ; }

[ -f "$ENV_FILE" ] || fail "no .env at $ENV_FILE"

RESTIC="$(command -v restic || echo /opt/homebrew/bin/restic)"
[ -x "$RESTIC" ] || fail "restic not installed (run: brew install restic)"

export RESTIC_PASSWORD="$(getenv RESTIC_PASSWORD)"
[ -n "$RESTIC_PASSWORD" ] || fail "RESTIC_PASSWORD not set in .env"

LOCAL_REPO="$(getenv BACKUP_LOCAL_REPO)"
B2_REPO="$(getenv BACKUP_B2_REPO)"
HC_URL="$(getenv BACKUP_HEALTHCHECK_URL)"
VAULT_PATH="$(getenv OBSIDIAN_VAULT_PATH)"
SUBFOLDER="$(getenv OBSIDIAN_SUBFOLDER)"; SUBFOLDER="${SUBFOLDER:-vMedical Agent}"
PHOTOS_PATH="$(getenv PHOTOS_PATH)"

# --- What to back up ---------------------------------------------------------
SOURCES=()
[ -d "$APP_DIR/data" ] && SOURCES+=("$APP_DIR/data")
[ -f "$ENV_FILE" ] && SOURCES+=("$ENV_FILE")
if [ -n "$VAULT_PATH" ]; then
  if [ -d "$VAULT_PATH/$SUBFOLDER" ]; then SOURCES+=("$VAULT_PATH/$SUBFOLDER")
  elif [ -d "$VAULT_PATH" ]; then SOURCES+=("$VAULT_PATH"); fi
fi
if [ -n "$PHOTOS_PATH" ] && [ -d "$PHOTOS_PATH" ]; then
  case "$PHOTOS_PATH" in "$APP_DIR/data"*) ;; *) SOURCES+=("$PHOTOS_PATH");; esac
fi
[ ${#SOURCES[@]} -gt 0 ] || fail "nothing to back up"

KEEP=(--keep-daily 7 --keep-weekly 4 --keep-monthly 6 --keep-yearly 2)
overall_ok=1
summary=""

backup_repo(){   # <label> <repo>
  local label="$1" repo="$2"
  export RESTIC_REPOSITORY="$repo"
  if ! "$RESTIC" cat config >/dev/null 2>&1; then
    log "[$label] initializing repository"
    "$RESTIC" init >>"$LOG" 2>&1 || { log "[$label] init FAILED"; overall_ok=0; summary+="$label:init-fail "; unset RESTIC_REPOSITORY; return; }
  fi
  log "[$label] backing up ${#SOURCES[@]} source(s)..."
  if "$RESTIC" backup "${SOURCES[@]}" --tag auto --exclude "*.log" >>"$LOG" 2>&1; then
    "$RESTIC" forget "${KEEP[@]}" --prune >>"$LOG" 2>&1 || log "[$label] prune warning"
    log "[$label] OK"; summary+="$label:ok "
  else
    log "[$label] backup FAILED"; overall_ok=0; summary+="$label:FAIL "
  fi
  unset RESTIC_REPOSITORY
}

did_any=0
if [ -n "$LOCAL_REPO" ]; then did_any=1; backup_repo "local" "$LOCAL_REPO"; fi
if [ -n "$B2_REPO" ]; then
  did_any=1
  export B2_ACCOUNT_ID="$(getenv B2_ACCOUNT_ID)" B2_ACCOUNT_KEY="$(getenv B2_ACCOUNT_KEY)"
  backup_repo "cloud" "$B2_REPO"
fi
[ "$did_any" -eq 1 ] || fail "no destination set (BACKUP_LOCAL_REPO and/or BACKUP_B2_REPO)"

if [ "$overall_ok" -eq 1 ]; then
  echo "$(date '+%Y-%m-%dT%H:%M:%S') OK $summary" > "$STATUS_FILE"
  log "Backup complete: $summary"
  [ -n "$HC_URL" ] && curl -fsS --max-time 15 "$HC_URL" >/dev/null 2>&1 || true
  exit 0
else
  echo "$(date '+%Y-%m-%dT%H:%M:%S') FAIL $summary" > "$STATUS_FILE"
  log "Backup had failures: $summary"
  [ -n "$HC_URL" ] && curl -fsS --max-time 15 "${HC_URL%/}/fail" >/dev/null 2>&1 || true
  exit 1
fi
