# Drone Control API Contracts (PR1 Baseline)

This document captures the compatibility surface currently consumed during migration.
It is intentionally signature-focused and test-backed by `tests/test_drone_control_contracts.py`.

## App imports (`backend/app.py`)

- `return_to_base(asset_id: str) -> dict` (async)
- `recall_swarm(asset_ids: list[str]) -> dict` (async)
- `set_drone_speed(asset_id: str, speed: float) -> None`
- `list_all_drones() -> dict` (async)

## MCP imports (`backend/mcp/server.py`)

- `deploy_swarm(asset_ids: list[str], formation: str = "spread") -> dict` (async)
- `recall_swarm(asset_ids: list[str]) -> dict` (async)

## Test and workflow compatibility imports (`tests/*`, agents)

- `plan_building_vertical_sweep(target_x, target_z, level_step=3.0, standoff=2.0, flood_clearance=0.5, approach_x=None, approach_z=None) -> dict`
- `assign_fleet_to_buildings(buildings: list[dict]) -> dict` (async)
- `parallel_fleet_scan(assignments: list[dict], unassigned_buildings: list[dict] | None = None) -> dict` (async)
- `parallel_fleet_supply(assignments: list[dict], unassigned_buildings: list[dict] | None = None, unassigned_targets: list[dict] | None = None) -> dict` (async)
- `register_detected_survivors(rows: Iterable[dict]) -> int`
- `clear_detected_survivors() -> None`

## Canonical import surface

`backend.services.api` is the stable import surface for app routes and MCP tools.
`backend.services.api.control` is the canonical control implementation used by
tests and internal orchestration call sites.
