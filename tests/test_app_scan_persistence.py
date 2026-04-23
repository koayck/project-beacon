from __future__ import annotations

import backend.app as app_module


def test_extract_scanned_building_rows_from_sweep_payload() -> None:
    payload = {
        "success": True,
        "building": {"id": 5, "x": -23.0, "z": -28.0},
        "unique_survivors_detected": [
            {"id": 101, "x": -24.2, "y": 6.0, "z": -27.4},
            {"id": 102, "x": -22.8, "y": 9.0, "z": -29.1},
        ],
    }

    rows = app_module._extract_scanned_building_rows(payload)

    assert rows == [
        {
            "building_id": 5,
            "detected_survivors": [
                {"x": -24.2, "y": 6.0, "z": -27.4},
                {"x": -22.8, "y": 9.0, "z": -29.1},
            ],
        }
    ]


def test_extract_scanned_building_rows_from_parallel_results() -> None:
    payload = {
        "results": [
            {
                "asset_id": "BEACON-01",
                "result": {
                    "building": {"id": 5},
                    "detected_survivors": [
                        {"x": 1.0, "y": 2.0, "z": 3.0},
                    ],
                },
            },
            {
                "asset_id": "BEACON-02",
                "result": {
                    "building": {"id": 7},
                    "detected_survivors": [
                        {"x": 4.0, "y": 5.0, "z": 6.0},
                    ],
                },
            },
        ]
    }

    rows = app_module._extract_scanned_building_rows(payload)

    assert rows == [
        {
            "building_id": 5,
            "detected_survivors": [{"x": 1.0, "y": 2.0, "z": 3.0}],
        },
        {
            "building_id": 7,
            "detected_survivors": [{"x": 4.0, "y": 5.0, "z": 6.0}],
        },
    ]


def test_extract_scanned_building_rows_ignores_missing_building_id() -> None:
    payload = {
        "unique_survivors_detected": [
            {"x": 1.0, "y": 2.0, "z": 3.0},
        ]
    }

    rows = app_module._extract_scanned_building_rows(payload)

    assert rows == []


def test_extract_scanned_building_rows_merges_repeated_building_rows() -> None:
    payload = {
        "results": [
            {
                "result": {
                    "building": {"id": 5},
                    "detected_survivors": [],
                }
            },
            {
                "result": {
                    "building": {"id": 5},
                    "detected_survivors": [{"x": 9.0, "y": 8.0, "z": 7.0}],
                }
            },
        ]
    }

    rows = app_module._extract_scanned_building_rows(payload)

    assert rows == [
        {
            "building_id": 5,
            "detected_survivors": [{"x": 9.0, "y": 8.0, "z": 7.0}],
        }
    ]
