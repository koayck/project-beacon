# Starlink Wi-Fi Triggered Docker Network Mock

This document explains the host-side logic that automatically applies a Starlink-like network profile to running Project Beacon drone containers when your active Wi-Fi SSID matches `Starlink` (or a custom SSID).

## What this mock does

When enabled, the scripts apply Linux `tc netem` rules to container `eth0`:

- **Starlink profile**: `delay 35ms 8ms`, `loss 0.8%`, `rate 150mbit`
- **Degraded profile**: `delay 75ms 40ms`, `loss 3%`, `rate 50mbit`
- **Direct profile**: clears all netem rules

This lets you test cloud model behavior under realistic Starlink-like conditions while still running local containers.

## Files added

- `scripts/toggle_starlink_tc.sh`
  - One-shot script: apply/clear/status for tc rules across beacon containers.
- `scripts/watch_starlink_wifi.sh`
  - Polling watcher: checks active SSID via `nmcli`, switches mode automatically.
- `scripts/install_starlink_nm_dispatcher.sh`
  - Installs a NetworkManager dispatcher hook for event-driven auto-switching.
- `backend/app.py`
  - Adds `GET /network/mock-status` for frontend visibility.
- `frontend/src/lib/api.ts`
  - Adds `getNetworkMockStatus()`.
- `frontend/src/components/scene.tsx`
  - Polls mock status every 3s.
- `frontend/src/components/panels/TopStatusBar.tsx`
  - Displays connectivity badge: `STARLINK MOCK ACTIVE/DEGRADED` or `DIRECT LINK`.

## Runtime status file

`scripts/toggle_starlink_tc.sh` writes `.starlink-mock-status` at repo root.

Example:

```ini
mode=starlink
updated_at=2026-03-19T16:00:00+00:00
source=watcher
target_ssid=Starlink
active_ssids=Starlink
container_count=5
```

The backend endpoint reads this file and returns it to the frontend.

## Prerequisites

1. Linux host with NetworkManager (`nmcli` available).
2. Docker running.
3. Rebuild drone images (needed once) because `iproute2` is installed in `drone-sim/Dockerfile`:

```bash
docker compose build beacon-01 beacon-02 beacon-03 beacon-04 beacon-05
docker compose up -d
```

`docker-compose.yml` includes `NET_ADMIN` capability so `tc` can run inside containers.

## Usage

### Manual one-shot mode

```bash
# Apply Starlink profile
bash scripts/toggle_starlink_tc.sh starlink

# Clear profile (direct)
bash scripts/toggle_starlink_tc.sh direct

# Inspect current qdisc mode
bash scripts/toggle_starlink_tc.sh status
```

### Auto mode (polling watcher)

```bash
TARGET_SSID=Starlink bash scripts/watch_starlink_wifi.sh
```

Behavior:
- Connected to SSID `Starlink` -> applies `starlink`
- Connected to any other SSID (or disconnected) -> applies `direct`

### Auto mode (NetworkManager dispatcher)

Install once:

```bash
sudo TARGET_SSID=Starlink bash scripts/install_starlink_nm_dispatcher.sh
```

This installs:

`/etc/NetworkManager/dispatcher.d/90-project-beacon-starlink-tc`

On network changes, it automatically toggles tc mode.

## Frontend visibility

The top bar shows:

- `STARLINK MOCK ACTIVE • SSID Starlink`
- `STARLINK MOCK DEGRADED • SSID Starlink`
- `DIRECT LINK`

Source of truth: `GET http://localhost:8000/network/mock-status`

## Notes

- SSID name is only a trigger condition; it does not change real network routing.
- If no beacon containers are running, scripts report unavailable and do not apply tc.
- You can change the trigger SSID with `TARGET_SSID=<your-ssid>`.
