from __future__ import annotations

from collections.abc import Iterable

from backend.grpc.client import DroneGrpcClient
from backend.runtime import grpc_client as _runtime_grpc_client
from backend.services.core import survivor_registry
from backend.world import model as world_model

# Mutable reference supports test injection while keeping a single source of truth.
_grpc_client: DroneGrpcClient = _runtime_grpc_client


def get_grpc_client() -> DroneGrpcClient:
    return _grpc_client


def set_grpc_client(client: DroneGrpcClient | None) -> None:
    global _grpc_client
    _grpc_client = client if client is not None else _runtime_grpc_client


def get_world_model_module():
    return world_model


def get_world():
    return world_model.WORLD


def get_window_scan_standoff_m() -> float:
    return world_model.WINDOW_SCAN_STANDOFF_M


def get_building_proximity_margin_m() -> float:
    return world_model.BUILDING_PROXIMITY_MARGIN_M


def get_flood_level() -> float:
    return world_model.FLOOD_LEVEL


def get_floor_height_m() -> float:
    return world_model.FLOOR_HEIGHT_M


def register_detected_survivors(rows: Iterable[dict]) -> int:
    return survivor_registry.register_detected_survivors(rows)


def clear_detected_survivors() -> None:
    survivor_registry.clear_detected_survivors()


def get_detected_survivor_ids() -> set[int]:
    return survivor_registry.get_detected_survivor_ids()
