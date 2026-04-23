#!/usr/bin/env bash
set -euo pipefail

TARGET_SSID="${TARGET_SSID:-Starlink}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-3}"
LAST_MODE=""
LAST_SSIDS=""
FORCE_STARLINK_AFTER_DISCONNECT="${FORCE_STARLINK_AFTER_DISCONNECT:-1}"
FORCE_RETRY_EVERY_CYCLES="${FORCE_RETRY_EVERY_CYCLES:-3}"
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

attempt_wifi_connection() {
  local target_ssid="$1"
  echo "[starlink-wifi-watch] attempting to connect to: ${target_ssid}"
  
  # Get the WiFi device name (usually wlan0, wlan1, etc.)
  local wifi_device
  wifi_device=$(nmcli -t -f device,type dev | grep wifi | head -1 | cut -d: -f1)
  
  if [[ -z "$wifi_device" ]]; then
    echo "[starlink-wifi-watch] no wifi device found"
    return 1
  fi
  
  # Enable WiFi if disabled
  nmcli radio wifi on 2>/dev/null || true
  
  # Try to connect to the target SSID
  # First check if connection profile exists, if not create it
  if nmcli connection show --active | grep -q "$target_ssid"; then
    echo "[starlink-wifi-watch] already connected to ${target_ssid}"
    return 0
  fi
  
  if nmcli connection show | grep -q "$target_ssid"; then
    # Profile exists, activate it
    echo "[starlink-wifi-watch] activating connection: ${target_ssid}"
    nmcli connection up "$target_ssid" 2>/dev/null || true
  else
    # Profile doesn't exist, try to connect via SSID scan
    echo "[starlink-wifi-watch] connecting to SSID: ${target_ssid}"
    nmcli device wifi connect "$target_ssid" --ifname "$wifi_device" 2>/dev/null || true
  fi
  
  # Wait a moment for connection to establish
  sleep 2
  
  # Verify connection
  if grep -Fxq "$target_ssid" <<<"$(current_ssid || true)"; then
    echo "[starlink-wifi-watch] successfully connected to ${target_ssid}"
    return 0
  else
    echo "[starlink-wifi-watch] failed to connect to ${target_ssid}"
    return 1
  fi
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
  local attempt_counter=0
  local force_starlink=0
  local had_wifi=0
  while true; do
    local ssids
    ssids="$(current_ssid || true)"
    mode="$(resolve_mode)"

    if [[ -n "$ssids" ]]; then
      had_wifi=1
    elif [[ "$had_wifi" -eq 1 && "$FORCE_STARLINK_AFTER_DISCONNECT" == "1" ]]; then
      # If WiFi was connected and then dropped, prefer reconnecting to target SSID.
      force_starlink=1
      had_wifi=0
      echo "[starlink-wifi-watch] disconnect detected; enabling Starlink preference"
    fi

    if grep -Fxq "$TARGET_SSID" <<<"$ssids"; then
      force_starlink=0
    fi

    # Refresh status when mode changes OR connected SSID list changes.
    if [[ "$mode" != "$LAST_MODE" || "$ssids" != "$LAST_SSIDS" ]]; then
      apply_mode "$mode"
      LAST_MODE="$mode"
      LAST_SSIDS="$ssids"
      attempt_counter=0
    fi

    # Auto-attempt target SSID when offline OR while Starlink preference is active.
    # The preference is enabled after a disconnect event and remains until target SSID is connected.
    if [[ -z "$ssids" || "$force_starlink" -eq 1 ]]; then
      attempt_counter=$((attempt_counter + 1))
      if [[ $((attempt_counter % FORCE_RETRY_EVERY_CYCLES)) -eq 0 ]]; then
        echo "[starlink-wifi-watch] retry #${attempt_counter}: attempting WiFi reconnection"
        attempt_wifi_connection "$TARGET_SSID" || true
      fi
    else
      attempt_counter=0
    fi
    
    sleep "$CHECK_INTERVAL_SECONDS"
  done
}

main
