#!/usr/bin/env bash
# scripts/crawl/install_launchd.sh — provision the CRAWL daily runner (macOS).
#
# Fills the launchd template with this repo's paths and installs/loads it as a
# per-user LaunchAgent. Idempotent: re-running re-installs and reloads. The job
# runs scripts/crawl_daily.sh once a day (09:15 local), producing a DRAFT PR
# for batch review — no auto-merge (ADR 0182, manual-handoff).
#
# Usage:
#   scripts/crawl/install_launchd.sh            # install + load
#   scripts/crawl/install_launchd.sh --uninstall  # unload + remove
#   scripts/crawl/install_launchd.sh --dry-run    # print the filled plist only

set -euo pipefail

LABEL="com.chimera.crawl"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE="$REPO_ROOT/scripts/crawl/com.chimera.crawl.plist.template"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV_BIN="$(command -v uv || true)"
UV_DIR="$(dirname "${UV_BIN:-/usr/local/bin/uv}")"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl unload "$DEST" 2>/dev/null || true
  rm -f "$DEST"
  echo "[crawl] uninstalled $LABEL"
  exit 0
fi

if [ -z "$UV_BIN" ]; then
  echo "[crawl] ERROR: uv not on PATH — install uv or fix PATH first." >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/state/crawl"

FILLED="$(sed \
  -e "s#__REPO__#$REPO_ROOT#g" \
  -e "s#__UVDIR__#$UV_DIR#g" \
  -e "s#__HOME__#$HOME#g" \
  "$TEMPLATE")"

if [ "${1:-}" = "--dry-run" ]; then
  echo "$FILLED"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
printf '%s\n' "$FILLED" > "$DEST"
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"
echo "[crawl] installed + loaded $LABEL → $DEST"
echo "[crawl]   schedule: daily 09:15 local"
echo "[crawl]   logs:     $REPO_ROOT/state/crawl/crawl.{out,err}.log"
echo "[crawl]   run now:  launchctl start $LABEL"
echo "[crawl]   status:   launchctl list | grep $LABEL"
echo "[crawl]   remove:   $0 --uninstall"
