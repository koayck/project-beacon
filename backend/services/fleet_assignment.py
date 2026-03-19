from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable


async def assign_fleet_to_buildings(
    buildings: list[dict],
    *,
    registered_asset_ids: Callable[[], list[str]],
    get_status: Callable[[str], Awaitable[dict]],
    is_eligible_idle_drone: Callable[[dict], bool],
    no_eligible_drones_result: Callable[[list[dict | Exception]], dict],
) -> dict:
    """
    Assign the closest available drones to buildings using greedy nearest-first matching.
    """
    if not buildings:
        return {"assignments": [], "unassigned_buildings": [], "idle_drones": []}

    asset_ids = registered_asset_ids()
    if not asset_ids:
        return {
            "error": "No drones uplinked.",
            "suggestion": "Use /uplink to connect a drone first.",
            "assignments": [],
            "unassigned_buildings": buildings,
        }

    statuses = await asyncio.gather(
        *[get_status(asset_id) for asset_id in asset_ids],
        return_exceptions=True,
    )

    eligible: list[dict] = []
    for status in statuses:
        if isinstance(status, Exception):
            continue
        if not is_eligible_idle_drone(status):
            continue
        eligible.append(status)

    if not eligible:
        no_eligible = no_eligible_drones_result(statuses)
        return {
            **no_eligible,
            "assignments": [],
            "unassigned_buildings": buildings,
        }

    remaining_drones = list(eligible)
    remaining_buildings = list(buildings)
    assignments: list[dict] = []

    while remaining_buildings and remaining_drones:
        best_drone: dict | None = None
        best_building: dict | None = None
        best_distance = float("inf")

        for drone in remaining_drones:
            for building in remaining_buildings:
                distance = math.sqrt(
                    (drone["x"] - building["x"]) ** 2 + (drone["z"] - building["z"]) ** 2
                )
                if distance < best_distance:
                    best_distance = distance
                    best_drone = drone
                    best_building = building

        if best_drone is None or best_building is None:
            break

        assignments.append(
            {
                "asset_id": best_drone["asset_id"],
                "building": best_building,
                "distance_m": round(best_distance, 1),
            }
        )
        remaining_drones = [
            drone
            for drone in remaining_drones
            if drone["asset_id"] != best_drone["asset_id"]
        ]
        remaining_buildings = [
            building for building in remaining_buildings if building is not best_building
        ]

    return {
        "assignments": assignments,
        "unassigned_buildings": remaining_buildings,
        "idle_drones": [drone["asset_id"] for drone in remaining_drones],
        "total_assigned": len(assignments),
    }


async def parallel_fleet_scan(
    assignments: list[dict],
    *,
    sweep_scan_building: Callable[[str, dict], Awaitable[dict]],
    unassigned_buildings: list[dict] | None = None,
) -> dict:
    """
    Execute sweep scans for all drone-building assignments concurrently.
    """
    if not assignments:
        return {"error": "No assignments provided.", "results": [], "total_survivors": 0}

    async def _scan_one(asset_id: str, building: dict) -> dict:
        result = await sweep_scan_building(asset_id, building)
        return {"asset_id": asset_id, "building": building, "scan_result": result}

    batch = await asyncio.gather(
        *[_scan_one(a["asset_id"], a["building"]) for a in assignments],
        return_exceptions=True,
    )

    all_results: list[dict] = []
    for index, result in enumerate(batch):
        if isinstance(result, Exception):
            all_results.append(
                {
                    "asset_id": assignments[index]["asset_id"],
                    "building": assignments[index]["building"],
                    "scan_result": {"error": str(result)},
                }
            )
        else:
            all_results.append(result)

    if unassigned_buildings:
        fallback_asset_id = assignments[0]["asset_id"]
        for building in unassigned_buildings:
            result = await sweep_scan_building(fallback_asset_id, building)
            all_results.append(
                {
                    "asset_id": fallback_asset_id,
                    "building": building,
                    "scan_result": result,
                }
            )

    total_survivors = 0
    building_summaries: list[str] = []
    for result in all_results:
        scan = result["scan_result"]
        building = result["building"]
        if "error" in scan:
            building_summaries.append(
                f"Building at (x={building['x']}, z={building['z']}) [{result['asset_id']}]: "
                f"SCAN ERROR - {scan['error']}"
            )
            continue

        count: int = scan.get("reported_survivor_count", 0)
        levels = scan.get("level_count", "?")
        waypoints = scan.get("waypoint_count", "?")
        total_survivors += count
        line = (
            f"Building at (x={building['x']:.1f}, z={building['z']:.1f}) [{result['asset_id']}]: "
            f"{count} survivor(s) across {levels} level(s). Waypoints: {waypoints}."
        )
        unique_survivors: list[dict] = scan.get("unique_survivors_detected", [])
        if unique_survivors:
            survivor_lines = []
            for survivor in unique_survivors:
                submerged_tag = " [SUBMERGED — CRITICAL]" if survivor.get("submerged") else ""
                survivor_lines.append(
                    f"  - Survivor {survivor['id']}: "
                    f"({survivor['x']}, {survivor['y']}, {survivor['z']}){submerged_tag}"
                )
            if any(survivor.get("submerged") for survivor in unique_survivors):
                submerged_count = sum(
                    1 for survivor in unique_survivors if survivor.get("submerged")
                )
                line += f" [CRITICAL: {submerged_count} submerged]"
            line += "\n" + "\n".join(survivor_lines)
        building_summaries.append(line)

    total_buildings = len(all_results)
    divider = "=" * 39
    thin_divider = "-" * 39
    total_line = (
        "No heat signatures detected across all scanned buildings."
        if total_survivors == 0
        else f"TOTAL SURVIVORS DETECTED: {total_survivors}"
    )
    summary = (
        f"{divider}\n"
        f"  AREA SCAN COMPLETE - {total_buildings} building(s)\n"
        f"{divider}\n"
        + "\n".join(building_summaries)
        + f"\n{thin_divider}\n{total_line}\n{divider}"
    )

    return {
        "success": True,
        "results": all_results,
        "total_buildings_scanned": total_buildings,
        "total_survivors": total_survivors,
        "summary": summary,
    }
