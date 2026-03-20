"""
Scanning Orchestrator — deterministic scan execution logic.

Pure orchestration functions for thermal scanning and survivor detection.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from backend.services.api.control import (
    get_drone_status,
    sweep_scan_building,
)
from backend.orchestrator.navigation import (
    execute_navigation_sequence,
    Point3D,
)


@dataclass
class Building:
    """Building target for scanning."""
    id: Optional[int]
    center_x: float
    center_z: float
    height: float
    name: Optional[str] = None


@dataclass
class BuildingScanResult:
    """Result of scanning a single building."""
    success: bool
    building: Building
    survivors_detected: int
    battery_remaining: float
    scan_summary: str
    error: Optional[str] = None

    @classmethod
    def failure(cls, building: Building, error: str) -> "BuildingScanResult":
        return cls(
            success=False,
            building=building,
            survivors_detected=0,
            battery_remaining=0.0,
            scan_summary="",
            error=error
        )

    @classmethod
    def success(
        cls,
        building: Building,
        survivors: int,
        battery_remaining: float,
        summary: str
    ) -> "BuildingScanResult":
        return cls(
            success=True,
            building=building,
            survivors_detected=survivors,
            battery_remaining=battery_remaining,
            scan_summary=summary,
            error=None
        )


@dataclass
class AreaScanResult:
    """Result of scanning multiple buildings."""
    success: bool
    total_buildings: int
    buildings_scanned: int
    total_survivors: int
    scan_results: list[BuildingScanResult]
    summary: str


async def execute_single_building_scan(
    asset_id: str,
    building: Building,
    scan_radius: float = 8.0,
    min_battery_threshold: float = 20.0
) -> BuildingScanResult:
    """
    Execute complete scan sequence for one building.
    
    Pure function — no LLM calls, deterministic execution.
    
    Procedure:
        1. Navigate to position above building (rooftop + 5m)
        2. Check battery level
        3. Execute sweep scan
        4. Return consolidated result
    
    Args:
        asset_id: Drone identifier
        building: Building target
        scan_radius: Scan detection radius in meters
        min_battery_threshold: Minimum battery % to proceed
    
    Returns:
        BuildingScanResult with survivors detected and battery status
    """
    # 1. Navigate to position above building
    nav_result = await execute_navigation_sequence(
        asset_id=asset_id,
        target_x=building.center_x,
        target_z=building.center_z,
        target_y=building.height + 5.0  # 5m above rooftop
    )
    
    if not nav_result.success:
        return BuildingScanResult.failure(
            building=building,
            error=f"Navigation failed: {nav_result.error}"
        )
    
    # 2. Check battery before scan
    status = await get_drone_status(asset_id)
    if "error" in status:
        return BuildingScanResult.failure(
            building=building,
            error=f"Failed to get drone status: {status.get('error')}"
        )
    
    battery_pct = status.get("battery", 0)
    if battery_pct < min_battery_threshold:
        return BuildingScanResult.failure(
            building=building,
            error=f"Battery too low: {battery_pct}% (minimum: {min_battery_threshold}%)"
        )
    
    # 3. Execute sweep scan
    scan_result = await sweep_scan_building(
        asset_id=asset_id,
        target_x=building.center_x,
        target_z=building.center_z,
        scan_radius=scan_radius
    )
    
    if "error" in scan_result:
        return BuildingScanResult.failure(
            building=building,
            error=f"Scan failed: {scan_result.get('error')}"
        )
    
    # Extract survivor count
    survivors = scan_result.get("unique_survivor_count", 0)
    summary = scan_result.get("summary", f"Scanned building at ({building.center_x}, {building.center_z})")
    
    # Get final battery status
    final_status = await get_drone_status(asset_id)
    final_battery = final_status.get("battery", battery_pct)
    
    return BuildingScanResult.success(
        building=building,
        survivors=survivors,
        battery_remaining=final_battery,
        summary=summary
    )


async def execute_area_scan_mission(
    assignments: list[dict],
    scan_radius: float = 8.0
) -> AreaScanResult:
    """
    Execute parallel scan across multiple buildings with fleet assignment.
    
    Pure function — no LLM calls, deterministic execution.
    
    Args:
        assignments: List of dicts with 'asset_id' and 'building' keys
        scan_radius: Scan detection radius in meters
    
    Returns:
        AreaScanResult with consolidated scan results
    """
    if not assignments:
        return AreaScanResult(
            success=False,
            total_buildings=0,
            buildings_scanned=0,
            total_survivors=0,
            scan_results=[],
            summary="No building assignments provided"
        )
    
    # Convert assignments to Building objects
    tasks = []
    for assignment in assignments:
        asset_id = assignment.get("asset_id")
        building_dict = assignment.get("building", {})
        
        building = Building(
            id=building_dict.get("id"),
            center_x=building_dict.get("x", building_dict.get("center_x", 0.0)),
            center_z=building_dict.get("z", building_dict.get("center_z", 0.0)),
            height=building_dict.get("h", building_dict.get("height", 10.0)),
            name=building_dict.get("name")
        )
        
        tasks.append(execute_single_building_scan(asset_id, building, scan_radius))
    
    # Execute scans in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results
    scan_results = []
    total_survivors = 0
    buildings_scanned = 0
    
    for result in results:
        if isinstance(result, Exception):
            # Handle exception as failed scan
            scan_results.append(BuildingScanResult.failure(
                building=Building(id=None, center_x=0, center_z=0, height=0),
                error=str(result)
            ))
        elif isinstance(result, BuildingScanResult):
            scan_results.append(result)
            if result.success:
                buildings_scanned += 1
                total_survivors += result.survivors_detected
    
    # Generate summary
    summary = (
        f"Scanned {buildings_scanned}/{len(assignments)} buildings, "
        f"detected {total_survivors} survivor(s)"
    )
    
    return AreaScanResult(
        success=buildings_scanned > 0,
        total_buildings=len(assignments),
        buildings_scanned=buildings_scanned,
        total_survivors=total_survivors,
        scan_results=scan_results,
        summary=summary
    )
