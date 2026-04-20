from __future__ import annotations

import asyncio
import logging

from backend.services.api.control import move_drone_to, return_to_base

logger = logging.getLogger(__name__)

SCOUT_ASSET_ID = "BEACON-SCOUT"
SCOUT_ALTITUDE = 35.0
SCOUT_SPEED = 15.0
# Only record explored sectors once the scout is airborne — prevents the base-pad
# sector from being revealed while the drone is still grounded.
SCOUT_TRACKING_MIN_Y = 5.0
# Survivors must be within this many metres of a building (XZ edge) to count as
# a "thermal anomaly". Survivors on open ground are ignored so sectors with
# buildings but no at-risk occupants stay quiet.
THERMAL_ANOMALY_BUILDING_MARGIN_M = 2.0

# Grid covering the full World 2 (Hat Yai) ground plane (200x200).
GRID_ORIGIN_X = -100.0
GRID_ORIGIN_Z = -100.0
GRID_WIDTH = 200.0
GRID_DEPTH = 200.0
GRID_COLS = 5
GRID_ROWS = 5
TOTAL_SECTORS = GRID_COLS * GRID_ROWS

CELL_W = GRID_WIDTH / GRID_COLS
CELL_D = GRID_DEPTH / GRID_ROWS


# ── Sector helpers (mirrors frontend fogOfWar.ts) ──────────────────────────────

def _sector_id(col: int, row: int) -> str:
    return f"{chr(65 + row)}{col + 1}"


def position_to_sector(x: float, z: float) -> str | None:
    col = int((x - GRID_ORIGIN_X) / CELL_W)
    row = int((z - GRID_ORIGIN_Z) / CELL_D)
    if col < 0 or col >= GRID_COLS or row < 0 or row >= GRID_ROWS:
        return None
    return _sector_id(col, row)


def sector_bounds(sector_id: str) -> dict:
    """Return {minX, maxX, minZ, maxZ} for a sector ID like 'A1'."""
    row = ord(sector_id[0]) - 65
    col = int(sector_id[1:]) - 1
    return {
        "id": sector_id,
        "minX": GRID_ORIGIN_X + col * CELL_W,
        "maxX": GRID_ORIGIN_X + (col + 1) * CELL_W,
        "minZ": GRID_ORIGIN_Z + row * CELL_D,
        "maxZ": GRID_ORIGIN_Z + (row + 1) * CELL_D,
    }


# ── Server-side exploration tracker ─────────────────────────────────────────────

class ExplorationTracker:
    """
    Tracks which sectors have been explored by the scout drone.
    Updated from every telemetry heartbeat — runs at 10 Hz so we never
    miss a sector the scout passes through.
    """

    def __init__(self) -> None:
        self._explored: set[str] = set()
        self._pending_reveals: list[dict] = []
        # Tracking is gated on an explicit enable so that a reset (e.g. on
        # world switch) stays "clean" until the next sweep is deployed, even
        # while the scout is still airborne and emitting heartbeats.
        self._tracking_enabled: bool = False

    @property
    def explored_sectors(self) -> list[str]:
        return sorted(self._explored)

    @property
    def tracking_enabled(self) -> bool:
        return self._tracking_enabled

    def enable_tracking(self) -> None:
        self._tracking_enabled = True

    def disable_tracking(self) -> None:
        self._tracking_enabled = False

    def pop_pending_reveals(self) -> list[dict]:
        """Return and clear any sectors revealed since last call."""
        reveals = self._pending_reveals
        self._pending_reveals = []
        return reveals

    def process_heartbeat(self, payload: dict) -> str | None:
        """
        Called on every scout telemetry heartbeat.
        Returns the newly explored sector ID, or None if already explored,
        the scout is still grounded, or tracking is disabled.
        """
        if not self._tracking_enabled:
            return None

        y = payload.get("y", 0.0)
        if y < SCOUT_TRACKING_MIN_Y:
            return None

        x = payload.get("x", 0.0)
        z = payload.get("z", 0.0)
        sid = position_to_sector(x, z)
        if sid is None or sid in self._explored:
            return None

        self._explored.add(sid)
        reveal_info = self._build_reveal_info(sid)
        self._pending_reveals.append(reveal_info)
        logger.info("Scout explored sector %s — %s", sid, reveal_info)
        return sid

    def _build_reveal_info(self, sid: str) -> dict:
        """Build sector reveal data using the world model."""
        from backend.world.model import WORLD

        bounds = sector_bounds(sid)
        wm = WORLD

        def _in_sector(cx: float, cz: float) -> bool:
            return (
                bounds["minX"] <= cx < bounds["maxX"]
                and bounds["minZ"] <= cz < bounds["maxZ"]
            )

        mission_buildings = [b for b in wm.buildings if _in_sector(b.cx, b.cz)]
        decor_buildings = [d for d in wm.decor_buildings if _in_sector(d.cx, d.cz)]
        structure_count = len(mission_buildings) + len(decor_buildings)
        max_height = max(
            (b.h for b in mission_buildings),
            default=0.0,
        )
        max_height = max(
            max_height,
            max((d.h for d in decor_buildings), default=0.0),
        )

        # Only survivors that are inside or adjacent to a mission building
        # in this sector count as thermal anomalies — decor buildings are
        # empty props and survivors on open terrain aren't at-risk
        # occupants, so we skip both.
        survivors_in_buildings = [
            s for s in wm.survivors
            if _in_sector(s.x, s.z)
            and any(
                b.distance_xz(s.x, s.z) <= THERMAL_ANOMALY_BUILDING_MARGIN_M
                for b in mission_buildings
            )
        ]

        return {
            "sector_id": sid,
            "building_count": structure_count,
            "max_height": max_height,
            "thermal_anomalies": len(survivors_in_buildings) > 0,
            "survivor_count": len(survivors_in_buildings),
        }

    def reset(self) -> None:
        self._explored.clear()
        self._pending_reveals.clear()
        self._tracking_enabled = False


# Singleton tracker.
exploration_tracker = ExplorationTracker()


# ── Sweep pattern ───────────────────────────────────────────────────────────────

def generate_sweep_waypoints() -> list[tuple[float, float, float]]:
    """Return lawnmower-pattern waypoints at scout altitude."""
    waypoints: list[tuple[float, float, float]] = []
    for row in range(GRID_ROWS):
        z = GRID_ORIGIN_Z + (row + 0.5) * CELL_D
        cols = range(GRID_COLS) if row % 2 == 0 else range(GRID_COLS - 1, -1, -1)
        for col in cols:
            x = GRID_ORIGIN_X + (col + 0.5) * CELL_W
            waypoints.append((x, SCOUT_ALTITUDE, z))
    return waypoints


_sweep_task: asyncio.Task | None = None


async def ensure_scout_uplink() -> dict:
    """
    Ensure the scout drone is registered and connected. Returns a result
    dict with ``success`` True when the scout is ready, False otherwise.
    Safe to call repeatedly — a no-op once uplinked.
    """
    from backend.runtime import grpc_client
    from backend.services.api import ensure_uplink

    if SCOUT_ASSET_ID in grpc_client.registered_asset_ids():
        return {"success": True, "asset_id": SCOUT_ASSET_ID, "already_uplinked": True}
    try:
        await ensure_uplink(SCOUT_ASSET_ID)
    except KeyError:
        return {
            "success": False,
            "error": (
                f"{SCOUT_ASSET_ID} is not broadcasting — make sure the "
                "beacon-scout container is running."
            ),
        }
    except Exception as exc:
        return {"success": False, "error": f"Scout uplink failed: {exc}"}
    return {"success": True, "asset_id": SCOUT_ASSET_ID, "already_uplinked": False}


async def _move_scout_to(x: float, y: float, z: float, label: str) -> bool:
    """Move the scout to a point, returning True on success."""
    try:
        result = await move_drone_to(SCOUT_ASSET_ID, x, y, z, speed=SCOUT_SPEED)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Scout %s raised", label)
        return False
    if not result.get("success"):
        logger.warning("Scout %s failed: %s", label, result.get("message"))
        return False
    return True


async def run_scout_sweep() -> None:
    """Execute the full lawnmower sweep sequentially.

    Flow: climb to cruise altitude above base (tracking OFF) → enable
    tracking → lawnmower over every grid cell → disable tracking → return
    to base. Keeping tracking off during takeoff and RTB prevents the base
    pad sector from "revealing" before the scout has actually started
    surveying, and keeps the descent from re-pinging cells at low altitude.
    """
    try:
        # 1. Takeoff before tracking — climb straight up to cruise altitude.
        logger.info("Scout takeoff → (0, %.1f, 0)", SCOUT_ALTITUDE)
        await _move_scout_to(0.0, SCOUT_ALTITUDE, 0.0, "takeoff")

        # 2. Tracking ON once airborne at cruise altitude.
        exploration_tracker.enable_tracking()

        # 3. Lawnmower sweep over every grid cell.
        waypoints = generate_sweep_waypoints()
        logger.info("Scout sweep started — %d waypoints", len(waypoints))
        for i, (x, y, z) in enumerate(waypoints):
            logger.info("Scout waypoint %d/%d → (%.1f, %.1f, %.1f)", i + 1, len(waypoints), x, y, z)
            await _move_scout_to(x, y, z, f"waypoint {i + 1}")
        logger.info("Scout sweep complete — initiating return-to-base")

        # 4. Tracking OFF before RTB so descent doesn't re-reveal cells.
        exploration_tracker.disable_tracking()

        # 5. Return to base.
        try:
            await return_to_base(SCOUT_ASSET_ID)
            logger.info("Scout returned to base")
        except Exception:
            logger.exception("Scout RTB failed")
    except asyncio.CancelledError:
        logger.info("Scout sweep cancelled")
        raise
    finally:
        # Always leave tracking off when a sweep ends (success, cancel, or error).
        exploration_tracker.disable_tracking()


def start_scout_sweep() -> asyncio.Task:
    """Launch the sweep as a background asyncio task (idempotent).

    Returns the running task so callers (e.g. the agent tool) can await
    completion when they want to block until the sweep finishes.
    Tracking is enabled inside the task AFTER takeoff so pre-takeoff
    heartbeats at the base pad don't reveal the home sector prematurely.
    """
    global _sweep_task
    if _sweep_task and not _sweep_task.done():
        logger.info("Scout sweep already running")
        return _sweep_task
    _sweep_task = asyncio.create_task(run_scout_sweep())
    return _sweep_task


def cancel_scout_sweep() -> bool:
    """Cancel an in-flight sweep. Returns True if a sweep was running."""
    global _sweep_task
    exploration_tracker.disable_tracking()
    if _sweep_task is None or _sweep_task.done():
        return False
    _sweep_task.cancel()
    return True
