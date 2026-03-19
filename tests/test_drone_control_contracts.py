"""Compatibility contracts for backend.services.api.control."""
from __future__ import annotations

import inspect

import backend.services.api.control as drone_control


def _param_names(callable_obj) -> list[str]:
    return list(inspect.signature(callable_obj).parameters.keys())


def test_app_import_contract_signatures() -> None:
    assert _param_names(drone_control.return_to_base) == ["asset_id"]
    assert _param_names(drone_control.recall_swarm) == ["asset_ids"]
    assert _param_names(drone_control.set_drone_speed) == ["asset_id", "speed"]
    assert _param_names(drone_control.list_all_drones) == []


def test_mcp_import_contract_signatures() -> None:
    assert _param_names(drone_control.deploy_swarm) == ["asset_ids", "formation"]
    assert inspect.signature(drone_control.deploy_swarm).parameters["formation"].default == "spread"


def test_test_suite_contract_signatures() -> None:
    assert _param_names(drone_control.plan_building_vertical_sweep) == [
        "target_x",
        "target_z",
        "level_step",
        "standoff",
        "flood_clearance",
        "approach_x",
        "approach_z",
    ]
    assert _param_names(drone_control.assign_fleet_to_buildings) == ["buildings"]
    assert _param_names(drone_control.parallel_fleet_scan) == ["assignments", "unassigned_buildings"]
    assert _param_names(drone_control.parallel_fleet_supply) == [
        "assignments",
        "unassigned_buildings",
        "unassigned_targets",
    ]
    assert _param_names(drone_control.register_detected_survivors) == ["rows"]
    assert _param_names(drone_control.clear_detected_survivors) == []


def test_import_smoke_for_startup_paths() -> None:
    import backend.app as _app  # noqa: F401
    import backend.mcp.server as _mcp_server  # noqa: F401

