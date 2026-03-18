from __future__ import annotations

from backend.app import _extract_survivor_coords


def test_extract_survivor_coords_from_nested_scan_results() -> None:
    payload = {
        "results": [
            {
                "asset_id": "BEACON-01",
                "scan_result": {
                    "unique_survivors_detected": [
                        {"id": 1, "x": -14.5, "y": 6.65, "z": -20.5},
                        {"id": 2, "x": -13.5, "y": 9.65, "z": -21.0},
                    ],
                },
            },
            {
                "asset_id": "BEACON-02",
                "scan_result": {
                    "detected_survivors": [
                        {"id": 2, "x": -13.5, "y": 9.65, "z": -21.0, "distance": 2.1},
                        {"id": 3, "x": -23.0, "y": 12.65, "z": -22.0, "distance": 2.9},
                    ],
                },
            },
        ]
    }

    survivors = _extract_survivor_coords(payload)

    assert len(survivors) == 3
    assert {"x": -14.5, "y": 6.65, "z": -20.5} in survivors
    assert {"x": -13.5, "y": 9.65, "z": -21.0} in survivors
    assert {"x": -23.0, "y": 12.65, "z": -22.0} in survivors


def test_extract_survivor_coords_from_view_objects_only() -> None:
    payload = {
        "objects": [
            {"object_type": "building", "x": -15.0, "y": 0.0, "z": -20.0},
            {"object_type": "survivor", "object_id": 7, "x": -19.0, "y": 3.65, "z": -27.5},
            {"object_type": "survivor", "object_id": 7, "x": -19.0, "y": 3.65, "z": -27.5},
        ]
    }

    survivors = _extract_survivor_coords(payload)

    assert survivors == [{"x": -19.0, "y": 3.65, "z": -27.5}]
