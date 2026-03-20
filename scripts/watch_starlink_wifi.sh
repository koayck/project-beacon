#!/usr/bin/env bash
set -euo pipefail

TARGET_SSID="${TARGET_SSID:-Starlink}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-3}"
LAST_MODE=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOGGLE_SCRIPT="${SCRIPT_DIR}/toggle_starlink_tc.sh"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found. Install NetworkManager tools first."
  exit 1
fi

if [[ ! -x "$TOGGLE_SCRIPT" ]]; then
  echo "Toggle script not executable: ${TOGGLE_SCRIPT}"
  exit 1
fi

current_ssid() {
  # Prints active wifi SSID(s), one per line.
  nmcli -t -f active,ssid dev wifi 2>/dev/null | awk -F: '$1 == "yes" {print $2}'
}

resolve_mode() {
  local ssids
  ssids="$(current_ssid || true)"

  if grep -Fxq "$TARGET_SSID" <<<"$ssids"; then
    echo "starlink"
  else
    echo "direct"
  fi
}

apply_mode() {
  local mode="$1"
  echo "[starlink-wifi-watch] applying mode=${mode} (target_ssid=${TARGET_SSID})"
  if ! STARLINK_MOCK_SOURCE="watcher" TARGET_SSID="$TARGET_SSID" "$TOGGLE_SCRIPT" "$mode"; then
    echo "[starlink-wifi-watch] toggle failed; will retry on next check"
  fi
}

main() {
  echo "[starlink-wifi-watch] started. target_ssid=${TARGET_SSID}, interval=${CHECK_INTERVAL_SECONDS}s"
  while true; do
    mode="$(resolve_mode)"
    if [[ "$mode" != "$LAST_MODE" ]]; then
      apply_mode "$mode"
      LAST_MODE="$mode"
    fi
    sleep "$CHECK_INTERVAL_SECONDS"
  done
}

main
