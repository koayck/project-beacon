"""Tests for sweep scan summary survivor count formatting."""
from __future__ import annotations

from backend.services.api.control import _build_sweep_scan_report


def test_build_sweep_scan_report_uses_passed_survivor_count() -> None:
    report = _build_sweep_scan_report(
        asset_id="BEACON-01",
        building={"min_x": -19.0, "max_x": -11.0, "min_z": -24.0, "max_z": -16.0},
        levels=[2.0, 5.0],
        flood_level=1.4,
        waypoint_count=10,
        survivor_count=2,
        battery=88.0,
        sensor_summary="agl=10.0m terrain=airspace",
    )

    assert "Findings  : 2 heat signature(s) detected." in report
