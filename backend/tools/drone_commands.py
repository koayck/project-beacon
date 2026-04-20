"""Compatibility layer exposing drone command helpers under backend.tools.

This module preserves older import paths used by tests and scripts while routing
all behavior through the current service-layer implementations.
"""
from __future__ import annotations

from backend.services.api.control import (
    _wait_until_waypoint_reached,
    plan_building_vertical_sweep,
    resolve_scan_target,
    return_to_base,
    set_client,
    sweep_scan_building,
)
from backend.services.navigation.route_planner import plan_route

__all__ = [
    "_wait_until_waypoint_reached",
    "plan_building_vertical_sweep",
    "plan_route",
    "resolve_scan_target",
    "return_to_base",
    "set_client",
    "sweep_scan_building",
]
