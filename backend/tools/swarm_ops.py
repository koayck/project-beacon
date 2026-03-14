"""Compatibility wrappers over the shared drone control service layer."""
from __future__ import annotations

from backend.services.drone_control import (
    deploy_swarm as service_deploy_swarm,
    recall_swarm as service_recall_swarm,
)


async def deploy_swarm(asset_ids: list[str], formation: str = "spread") -> dict:
    """
    Deploy multiple drones in a named formation.
    Supported formations: 'spread', 'line', 'triangle'.
    """
    return await service_deploy_swarm(asset_ids, formation)


async def recall_swarm(asset_ids: list[str]) -> dict:
    """Command all drones in the list to return to base immediately."""
    return await service_recall_swarm(asset_ids)
