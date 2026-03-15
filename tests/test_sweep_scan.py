"""Tests for sweep_scan_building survivor-count summary fix.

The core bug being tested:
    Even when the drone sensor detects a survivor (red ray rendered in the
    3-D twin), the summary previously always reported "no heat signature
    detected" because ``survivors_in_range`` was set to
    ``len(survivors_in_scan_radius)`` — a purely geometric filter that can
    be zero even while survivors are visible.

The fix (see drone_control.py) sets ``survivors_in_range`` to the maximum of:
    1. ``len(detected_survivors)``        – survivors in the sensor view
    2. ``view["survivors_in_range"]``     – integer from the view payload

These tests verify that the summary text correctly reflects visible survivors.
"""

from __future__ import annotations

import math
import pytest

from backend.services.drone_control import (
    _compile_sweep_summary,
    sweep_scan_building,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_view(
    survivors_in_range: int | None = None,
    detected_survivors: list[dict] | None = None,
    summary: str = "",
) -> dict:
    """Build a synthetic sensor-view payload."""
    view: dict = {"summary": summary}
    if survivors_in_range is not None:
        view["survivors_in_range"] = survivors_in_range
    if detected_survivors is not None:
        view["detected_survivors"] = detected_survivors
    return view


async def _stub_view(view_payload: dict):
    """Async view fetcher that always returns the same payload."""
    async def _fetcher(drone_id: str, waypoint: dict) -> dict:
        return view_payload
    return _fetcher


# ---------------------------------------------------------------------------
# Unit tests for _compile_sweep_summary
# ---------------------------------------------------------------------------


class TestCompileSweepSummary:
    def test_no_survivors_returns_no_heat_signature(self):
        reports = [{"survivors_in_range": 0, "detected_survivors": []}]
        summary = _compile_sweep_summary(reports)
        assert "No heat signature" in summary

    def test_single_survivor_singular_noun(self):
        reports = [
            {
                "survivors_in_range": 1,
                "detected_survivors": [{"id": "S1", "distance": 2.0}],
            }
        ]
        summary = _compile_sweep_summary(reports)
        assert "1 survivor" in summary
        assert "survivors" not in summary.replace("1 survivor", "")

    def test_multiple_survivors_plural_noun(self):
        reports = [
            {
                "survivors_in_range": 3,
                "detected_survivors": [
                    {"id": "S1", "distance": 1.5},
                    {"id": "S2", "distance": 2.0},
                    {"id": "S3", "distance": 3.0},
                ],
            }
        ]
        summary = _compile_sweep_summary(reports)
        assert "survivors" in summary

    def test_deduplicates_across_waypoints(self):
        """Same survivor seen from two waypoints counts once."""
        reports = [
            {"survivors_in_range": 1, "detected_survivors": [{"id": "S1", "distance": 1.0}]},
            {"survivors_in_range": 1, "detected_survivors": [{"id": "S1", "distance": 1.5}]},
        ]
        summary = _compile_sweep_summary(reports)
        assert "1 survivor" in summary

    def test_multiple_waypoints_zero_everywhere(self):
        reports = [
            {"survivors_in_range": 0, "detected_survivors": []},
            {"survivors_in_range": 0, "detected_survivors": []},
        ]
        summary = _compile_sweep_summary(reports)
        assert "No heat signature" in summary


# ---------------------------------------------------------------------------
# Integration tests for sweep_scan_building
# ---------------------------------------------------------------------------


class TestSweepScanBuilding:
    """Tests that exercise the full sweep_scan_building coroutine."""

    @pytest.mark.asyncio
    async def test_survivors_in_view_payload_reflected_in_summary(self):
        """Core regression: view reports survivors_in_range=2 but all survivors
        happen to be outside the geometric scan_radius filter → summary must
        still say survivors detected (not 'no heat signature').
        """
        # Survivors are 8 units away; scan_radius used for geometric filter is 5.
        far_survivor = {"id": "S1", "distance": 8.0}
        view = _make_view(
            survivors_in_range=2,
            detected_survivors=[far_survivor],
            summary="2 heat signatures detected",
        )

        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-01",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )

        report = result["waypoint_reports"][0]
        # survivors_within_scan_radius uses geometric filter → 0 (far away)
        assert report["survivors_within_scan_radius"] == 0
        # survivors_in_range uses max(len(detected), view count) → 2
        assert report["survivors_in_range"] == 2
        # Summary must not say "no heat signature"
        assert "No heat signature" not in result["summary"]
        assert result["total_survivors_visible"] == 2

    @pytest.mark.asyncio
    async def test_detected_survivors_list_used_when_no_view_count(self):
        """When view payload has no survivors_in_range key, fall back to
        len(detected_survivors)."""
        view = _make_view(
            survivors_in_range=None,  # key absent from payload
            detected_survivors=[{"id": "S1", "distance": 3.0}],
        )
        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-02",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )
        report = result["waypoint_reports"][0]
        assert report["survivors_in_range"] == 1
        assert "No heat signature" not in result["summary"]

    @pytest.mark.asyncio
    async def test_no_survivors_gives_no_heat_signature_summary(self):
        """All-zero case: no visible survivors → summary says no heat signature."""
        view = _make_view(survivors_in_range=0, detected_survivors=[])
        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-03",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )
        assert "No heat signature" in result["summary"]
        assert result["total_survivors_visible"] == 0

    @pytest.mark.asyncio
    async def test_max_taken_between_detected_and_view_count(self):
        """When view count exceeds len(detected_survivors), use view count."""
        # Only 1 entry in the list but view says 3 (sensor detected extras
        # without building individual records yet)
        view = _make_view(
            survivors_in_range=3,
            detected_survivors=[{"id": "S1", "distance": 1.0}],
        )
        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-04",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )
        assert result["waypoint_reports"][0]["survivors_in_range"] == 3

    @pytest.mark.asyncio
    async def test_survivors_within_scan_radius_uses_geometric_filter(self):
        """survivors_within_scan_radius must only count entries where
        distance <= scan_radius."""
        survivors = [
            {"id": "S1", "distance": 3.0},   # inside radius
            {"id": "S2", "distance": 7.0},   # outside radius
            {"id": "S3", "distance": float("nan")},  # invalid distance
        ]
        view = _make_view(survivors_in_range=3, detected_survivors=survivors)
        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-05",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )
        report = result["waypoint_reports"][0]
        # Only S1 is within radius=5
        assert report["survivors_within_scan_radius"] == 1
        # But visible count is max(3, 3) = 3
        assert report["survivors_in_range"] == 3

    @pytest.mark.asyncio
    async def test_report_includes_both_survivor_lists(self):
        """Waypoint report exposes both detected_survivors and
        detected_survivors_within_scan_radius for downstream consumers."""
        survivors = [
            {"id": "S1", "distance": 2.0},
            {"id": "S2", "distance": 9.0},
        ]
        view = _make_view(survivors_in_range=2, detected_survivors=survivors)
        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-06",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )
        report = result["waypoint_reports"][0]
        assert len(report["detected_survivors"]) == 2
        assert len(report["detected_survivors_within_scan_radius"]) == 1
        assert report["detected_survivors_within_scan_radius"][0]["id"] == "S1"

    @pytest.mark.asyncio
    async def test_multiple_levels_aggregated(self):
        """Multi-level sweep: total_survivors_visible sums over all waypoints."""
        view_with_survivor = _make_view(
            survivors_in_range=1,
            detected_survivors=[{"id": "S1", "distance": 2.0}],
        )
        view_empty = _make_view(survivors_in_range=0, detected_survivors=[])

        call_count = {"n": 0}

        async def alternating_fetcher(drone_id: str, waypoint: dict) -> dict:
            call_count["n"] += 1
            # First waypoint has a survivor, second does not.
            return view_with_survivor if call_count["n"] == 1 else view_empty

        result = await sweep_scan_building(
            drone_id="beacon-07",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0, 3.0],
            get_view=alternating_fetcher,
            points_per_level=1,
        )
        assert len(result["waypoint_reports"]) == 2
        assert result["total_survivors_visible"] == 1
        assert "No heat signature" not in result["summary"]

    @pytest.mark.asyncio
    async def test_non_integer_view_count_ignored(self):
        """If view['survivors_in_range'] is not an int (e.g. None or string),
        it should be ignored and len(detected_survivors) used instead."""
        view = _make_view(detected_survivors=[{"id": "S1", "distance": 1.0}])
        # Inject a non-integer survivors_in_range
        view["survivors_in_range"] = "two"
        fetcher = await _stub_view(view)
        result = await sweep_scan_building(
            drone_id="beacon-08",
            center_x=0.0,
            center_y=0.0,
            center_z=0.0,
            scan_radius=5.0,
            levels=[1.0],
            get_view=fetcher,
            points_per_level=1,
        )
        # "two" is not an int → fallback to len(detected_survivors) = 1
        assert result["waypoint_reports"][0]["survivors_in_range"] == 1
