"""
Orchestrator module — deterministic execution logic for drone operations.

This module provides pure functions that handle mission execution without
LLM calls. Agents use these orchestrators for reliable, fast execution.

Architecture:
- navigation.py: Movement sequences with automatic retry and obstacle avoidance
- scanning.py: Thermal scan sequences with battery checks and parallel execution

Usage:
    from backend.orchestrator.navigation import execute_navigation_sequence
    from backend.orchestrator.scanning import execute_single_building_scan
    
    # Deterministic navigation (no LLM calls)
    result = await execute_navigation_sequence("BEACON-01", 10.0, -5.0)
    
    # Deterministic scan (no LLM calls)
    scan = await execute_single_building_scan(
        "BEACON-01",
        Building(center_x=10, center_z=-5, height=15)
    )
"""

from backend.orchestrator.navigation import (
    execute_navigation_sequence,
    execute_return_to_base,
    Point3D,
    NavigationResult,
)
from backend.orchestrator.scanning import (
    execute_single_building_scan,
    execute_area_scan_mission,
    Building,
    BuildingScanResult,
    AreaScanResult,
)

__all__ = [
    "execute_navigation_sequence",
    "execute_return_to_base",
    "execute_single_building_scan",
    "execute_area_scan_mission",
    "Point3D",
    "NavigationResult",
    "Building",
    "BuildingScanResult",
    "AreaScanResult",
]
