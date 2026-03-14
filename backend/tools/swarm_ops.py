"""Compatibility wrappers over the shared drone control service layer."""
from __future__ import annotations

import asyncio

from backend.tools.drone_commands import _get_client, return_to_base

from backend.services.drone_control import (
    deploy_swarm as service_deploy_swarm,
    recall_swarm as service_recall_swarm,
)

# Pre-defined formation offsets (x, y, z) relative to base
_FORMATIONS: dict[str, list[tuple[float, float, float]]] = {
    "spread": [(0, 0, 10), (10, 0, 10), (-10, 0, 10), (0, 10, 10), (0, -10, 10)],
    "line": [(i * 8, 0, 10) for i in range(5)],
    "triangle": [(0, 0, 10), (6, 6, 10), (-6, 6, 10)],
}


async def deploy_swarm(asset_ids: list[str], formation: str = "spread") -> dict:
    """
    Deploy multiple drones in a named formation.
    Supported formations: 'spread', 'line', 'triangle'.
    """
    return await service_deploy_swarm(asset_ids, formation)


async def recall_swarm(asset_ids: list[str]) -> dict:
    """Command all drones in the list to return to base using safe routed return."""
    results_raw = await asyncio.gather(
        *[return_to_base(aid) for aid in asset_ids],
        return_exceptions=True,
    )
    results: list[dict] = []
    for aid, result in zip(asset_ids, results_raw):
        if isinstance(result, Exception):
            results.append({"asset_id": aid, "error": str(result)})
        else:
            results.append(result)
    return {"recalled": asset_ids, "results": list(results)}
