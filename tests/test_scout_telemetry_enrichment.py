from __future__ import annotations

import backend.app as app_module
import backend.services.scout as scout_module


class _FakeTracker:
    def __init__(self) -> None:
        self._explored = ["A1", "A2"]
        self._reveals = [{"sector_id": "A2", "building_count": 1, "max_height": 12.0, "thermal_anomalies": False, "survivor_count": 0}]
        self.process_calls = 0

    @property
    def explored_sectors(self) -> list[str]:
        return list(self._explored)

    def process_heartbeat(self, payload: dict) -> str | None:
        self.process_calls += 1
        return "A2"

    def pop_pending_reveals(self) -> list[dict]:
        reveals = list(self._reveals)
        self._reveals = []
        return reveals


def test_enrich_scout_telemetry_adds_exploration_fields(monkeypatch) -> None:
    tracker = _FakeTracker()
    monkeypatch.setattr(scout_module, "exploration_tracker", tracker)
    monkeypatch.setattr(scout_module, "SCOUT_ASSET_ID", "BEACON-SCOUT")

    original = {"asset_id": "BEACON-SCOUT", "x": 10.0, "y": 35.0, "z": -20.0}
    enriched = app_module._enrich_scout_telemetry(original)

    assert tracker.process_calls == 1
    assert "explored_sectors" not in original
    assert enriched["explored_sectors"] == ["A1", "A2"]
    assert enriched["sector_reveals"] == [
        {
            "sector_id": "A2",
            "building_count": 1,
            "max_height": 12.0,
            "thermal_anomalies": False,
            "survivor_count": 0,
        }
    ]


def test_enrich_scout_telemetry_leaves_non_scout_payload_unchanged(monkeypatch) -> None:
    tracker = _FakeTracker()
    monkeypatch.setattr(scout_module, "exploration_tracker", tracker)
    monkeypatch.setattr(scout_module, "SCOUT_ASSET_ID", "BEACON-SCOUT")

    original = {"asset_id": "BEACON-01", "x": 0.0, "y": 2.0, "z": 0.0}
    enriched = app_module._enrich_scout_telemetry(original)

    assert tracker.process_calls == 0
    assert enriched == original
    assert enriched is not original
