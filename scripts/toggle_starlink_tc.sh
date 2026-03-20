#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-starlink}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STATUS_FILE="${REPO_ROOT}/.starlink-mock-status"
TARGET_SSID="${TARGET_SSID:-Starlink}"
SOURCE="${STARLINK_MOCK_SOURCE:-manual}"

# Starlink-like profile tuned for realistic LEO behavior.
STARLINK_QDISC="delay 35ms 8ms distribution normal loss 0.8% rate 150mbit"
DEGRADED_QDISC="delay 75ms 40ms distribution normal loss 3% rate 50mbit"

compose_beacon_containers() {
  (
    cd "${REPO_ROOT}"
    docker compose ps -q beacon-01 beacon-02 beacon-03 beacon-04 beacon-05 2>/dev/null | sed '/^$/d'
  )
}

all_beacon_containers() {
  {
    compose_beacon_containers
    docker ps --format '{{.ID}} {{.Names}}' | awk '$2 ~ /beacon-[0-9][0-9]/ {print $1}'
  } | awk '!seen[$0]++'
}

container_name() {
  docker inspect --format '{{.Name}}' "$1" | sed 's#^/##'
}

run_in_container() {
  local container_id="$1"
  shift
  docker exec "$container_id" "$@"
}

apply_qdisc() {
  local container_id="$1"
  local qdisc_args="$2"
  run_in_container "$container_id" tc qdisc replace dev eth0 root netem ${qdisc_args}
}

clear_qdisc() {
  local container_id="$1"
  run_in_container "$container_id" tc qdisc del dev eth0 root 2>/dev/null || true
}

show_qdisc() {
  local container_id="$1"
  run_in_container "$container_id" tc qdisc show dev eth0 2>/dev/null || true
}

active_ssids() {
  if ! command -v nmcli >/dev/null 2>&1; then
    return 0
  fi
  nmcli -t -f active,ssid dev wifi 2>/dev/null | awk -F: '$1 == "yes" {print $2}' | paste -sd ',' -
}

infer_mode_from_containers() {
  local total="$#"
  local starlink=0
  local degraded=0
  local direct=0
  local custom=0

  if [[ "$total" -eq 0 ]]; then
    echo "unavailable"
    return
  fi

  for cid in "$@"; do
    local qdisc
    qdisc="$(show_qdisc "$cid" | tr '\n' ' ')"

    if [[ "$qdisc" != *"netem"* ]]; then
      direct=$((direct + 1))
      continue
    fi

    if [[ "$qdisc" == *"loss 0.8%"* && "$qdisc" == *"rate 150Mbit"* ]]; then
      starlink=$((starlink + 1))
    elif [[ "$qdisc" == *"loss 3%"* && "$qdisc" == *"rate 50Mbit"* ]]; then
      degraded=$((degraded + 1))
    else
      custom=$((custom + 1))
    fi
  done

  if [[ "$starlink" -eq "$total" ]]; then
    echo "starlink"
  elif [[ "$degraded" -eq "$total" ]]; then
    echo "degraded"
  elif [[ "$direct" -eq "$total" ]]; then
    echo "direct"
  else
    echo "mixed"
  fi
}

write_status_file() {
  local mode="$1"
  local container_count="$2"
  local now
  now="$(date -Iseconds)"
  local ssids
  ssids="$(active_ssids || true)"

  cat >"${STATUS_FILE}" <<STATUS
mode=${mode}
updated_at=${now}
source=${SOURCE}
target_ssid=${TARGET_SSID}
active_ssids=${ssids}
container_count=${container_count}
STATUS
}

print_status() {
  local mode="$1"
  shift
  local count="$#"
  echo "Mode: ${mode}"
  echo "Target SSID: ${TARGET_SSID}"
  echo "Active SSIDs: $(active_ssids || true)"
  echo "Containers: ${count}"
  for cid in "$@"; do
    local name
    name="$(container_name "$cid")"
    echo "- ${name}: $(show_qdisc "$cid" | tr '\n' ' ' | sed 's/  */ /g')"
  done
}

main() {
  mapfile -t containers < <(all_beacon_containers)

  if [[ ${#containers[@]} -eq 0 && "$MODE" != "status" ]]; then
    write_status_file "unavailable" "0"
    echo "No beacon containers are running. Start them with: docker compose up -d"
    exit 1
  fi

  local effective_mode=""

  case "$MODE" in
    starlink)
      echo "Applying Starlink tc profile to ${#containers[@]} beacon containers..."
      for cid in "${containers[@]}"; do
        apply_qdisc "$cid" "$STARLINK_QDISC"
      done
      effective_mode="starlink"
      ;;
    degraded)
      echo "Applying degraded Starlink tc profile to ${#containers[@]} beacon containers..."
      for cid in "${containers[@]}"; do
        apply_qdisc "$cid" "$DEGRADED_QDISC"
      done
      effective_mode="degraded"
      ;;
    direct|clear)
      echo "Clearing tc profile from ${#containers[@]} beacon containers..."
      for cid in "${containers[@]}"; do
        clear_qdisc "$cid"
      done
      effective_mode="direct"
      ;;
    status)
      effective_mode="$(infer_mode_from_containers "${containers[@]}")"
      ;;
    *)
      echo "Usage: $0 {starlink|degraded|direct|clear|status}"
      exit 2
      ;;
  esac

  write_status_file "$effective_mode" "${#containers[@]}"
  print_status "$effective_mode" "${containers[@]}"
}

main
