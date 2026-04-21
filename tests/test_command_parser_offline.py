from __future__ import annotations

from backend.agents.command_parser import parse_command
from backend.agents.schemas import MissionType


def test_parse_command_coordinates_xyz() -> None:
    intent = parse_command("Move BEACON-01 to coordinates (10, 20, -5)")
    assert intent.mission_type == MissionType.MOVE
    assert intent.asset_ids == ["BEACON-01"]
    assert intent.targets == [{"type": "coordinates", "x": 10.0, "y": 20.0, "z": -5.0}]


def test_parse_command_scan_building_with_context_and_constraints() -> None:
    intent = parse_command("Scan the flooded school for survivors urgently")
    assert intent.mission_type == MissionType.SCAN
    assert intent.asset_ids == ["auto"]
    assert intent.constraints == {"urgency": "high", "detect": "survivors"}
    assert intent.targets and intent.targets[0]["type"] == "building"
    assert intent.targets[0]["class"] == "school"
    assert intent.targets[0]["context"] == "flooded"


def test_parse_command_deploy_priority_over_scan_keyword() -> None:
    intent = parse_command("Deploy all drones to scan the district")
    assert intent.mission_type == MissionType.DEPLOY_SWARM
    assert intent.asset_ids == ["auto"]
    assert intent.targets == [{"type": "area", "name": "district"}]
    assert intent.is_complex_mission() is True


def test_parse_command_deploy_scout_sweep_phrase() -> None:
    intent = parse_command(
        "Deploy the scout drone to survey the disaster zone and map every sector."
    )
    assert intent.mission_type == MissionType.DEPLOY_SWARM
    assert intent.asset_ids == ["auto"]
    assert intent.constraints.get("operation") == "deploy_scout_sweep"
    assert intent.targets == [
        {"type": "area", "name": "disaster zone", "scope": "every sector"}
    ]
