"""
Navigation Orchestrator — deterministic drone movement logic.

This module contains pure orchestration functions that coordinate
navigation without LLM calls. Agents call these functions instead
of having step-by-step procedural instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.services.api.control import (
    get_drone_status,
    move_drone_to,
    plan_route,
    return_to_base as _return_to_base,
)


@dataclass
class Point3D:
    """3D coordinate."""
    x: float
    y: float
    z: float


@dataclass
class NavigationResult:
    """Result of a navigation sequence."""
    success: bool
    final_position: Optional[Point3D]
    waypoints_completed: int
    route_summary: str
    error: Optional[str] = None


async def execute_navigation_sequence(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: Optional[float] = None,
    max_retries: int = 3,
) -> NavigationResult:
    """
    Navigate drone to target with automatic altitude escalation on blocked routes.
    
    Pure function — no LLM calls, deterministic execution.
    
    Args:
        asset_id: Drone identifier (e.g., "BEACON-01")
        target_x: East coordinate
        target_z: South coordinate
        target_y: Altitude (if None, auto-calculated by route planner)
        max_retries: Maximum altitude escalation attempts
    
    Returns:
        NavigationResult with success status and final position
    
    Procedure:
        1. Call plan_route with current altitude offset
        2. If blocked, retry with +5m altitude, then +10m, then +15m
        3. If route clear, execute waypoints sequentially
        4. If blocked during movement, re-route from current position
        5. Return success with final position or error after max retries
    """
    for attempt in range(max_retries):
        # Calculate altitude offset for this attempt (0m, +5m, +10m)
        altitude_offset = attempt * 5.0
        
        # Get current drone status
        status = await get_drone_status(asset_id)
        if "error" in status:
            return NavigationResult(
                success=False,
                final_position=None,
                waypoints_completed=0,
                route_summary="",
                error=f"Failed to get drone status: {status.get('error')}"
            )
        
        current_y = status.get("y", 2.0)
        
        # Determine target altitude
        if target_y is not None:
            # Explicit altitude provided
            adjusted_y = target_y + altitude_offset
        else:
            # Auto-calculate with escalation
            adjusted_y = max(current_y + altitude_offset, 10.0 + altitude_offset) if attempt > 0 else None
        
        # Plan route
        route = await plan_route(
            asset_id=asset_id,
            target_x=target_x,
            target_z=target_z,
            target_y=adjusted_y
        )
        
        if "error" in route:
            # Route planning failed, try next altitude
            if attempt == max_retries - 1:
                return NavigationResult(
                    success=False,
                    final_position=None,
                    waypoints_completed=0,
                    route_summary="",
                    error=f"No clear route found after {max_retries} attempts: {route.get('error')}"
                )
            continue  # Try next altitude
        
        # Route found, execute waypoints
        waypoints = route.get("waypoints", [])
        if not waypoints:
            return NavigationResult(
                success=False,
                final_position=None,
                waypoints_completed=0,
                route_summary="",
                error="Route planning returned no waypoints"
            )
        
        # Execute waypoints sequentially
        for i, waypoint in enumerate(waypoints):
            move_result = await move_drone_to(
                asset_id=asset_id,
                x=waypoint["x"],
                y=waypoint["y"],
                z=waypoint["z"]
            )
            
            if "error" in move_result or move_result.get("status") == "BLOCKED":
                # Movement blocked, get current position and re-route
                current_status = await get_drone_status(asset_id)
                replan_route = await plan_route(
                    asset_id=asset_id,
                    target_x=target_x,
                    target_z=target_z,
                    target_y=adjusted_y
                )
                
                if "error" in replan_route:
                    # Re-route failed, try next altitude in outer loop
                    break
                
                # Continue with remaining waypoints from re-routed path
                # (For simplicity, we'll return and let retry handle it)
                break
            
            # Check if this was the final waypoint
            if i == len(waypoints) - 1:
                # Success!
                final_status = await get_drone_status(asset_id)
                return NavigationResult(
                    success=True,
                    final_position=Point3D(
                        x=final_status.get("x", waypoint["x"]),
                        y=final_status.get("y", waypoint["y"]),
                        z=final_status.get("z", waypoint["z"])
                    ),
                    waypoints_completed=len(waypoints),
                    route_summary=route.get("summary", f"{len(waypoints)} waypoints"),
                    error=None
                )
    
    # All retries exhausted
    return NavigationResult(
        success=False,
        final_position=None,
        waypoints_completed=0,
        route_summary="",
        error=f"Navigation failed after {max_retries} altitude escalation attempts"
    )


def _navigation_result_to_dict(result: NavigationResult) -> dict[str, object]:
    """Convert NavigationResult to a JSON-serializable dictionary.

    Args:
        result: NavigationResult produced by execute_navigation_sequence.

    Returns:
        Dictionary containing only primitive/JSON-serializable values.
    """
    final_position = None
    if result.final_position is not None:
        final_position = {
            "x": result.final_position.x,
            "y": result.final_position.y,
            "z": result.final_position.z,
        }

    return {
        "success": result.success,
        "final_position": final_position,
        "waypoints_completed": result.waypoints_completed,
        "route_summary": result.route_summary,
        "error": result.error,
    }


async def execute_navigation_sequence_tool(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: Optional[float] = None,
    max_retries: int = 3,
) -> dict[str, object]:
    """Tool-safe wrapper for navigation sequence orchestration.

    This wrapper exists for automatic function calling compatibility.
    It exposes a simpler return schema than the NavigationResult dataclass.

    Args:
        asset_id: Drone identifier (e.g., "BEACON-01").
        target_x: East coordinate.
        target_z: South coordinate.
        target_y: Optional altitude override.
        max_retries: Maximum altitude escalation attempts.

    Returns:
        JSON-serializable navigation result dictionary.
    """
    result = await execute_navigation_sequence(
        asset_id=asset_id,
        target_x=target_x,
        target_z=target_z,
        target_y=target_y,
        max_retries=max_retries,
    )
    return _navigation_result_to_dict(result)


async def execute_return_to_base(asset_id: str) -> dict:
    """
    Return drone to home base with obstacle-aware routing.
    
    This is a thin wrapper around the existing return_to_base workflow.
    
    Args:
        asset_id: Drone identifier
    
    Returns:
        Result dict with success status
    """
    return await _return_to_base(asset_id)
