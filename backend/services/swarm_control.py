
import asyncio
from collections.abc import Awaitable, Callable

from backend.runtime import grpc_client as _runtime_grpc_client

# Pre-defined formation offsets (x, y, z) relative to base.
_FORMATIONS: dict[str, list[tuple[float, float, float]]] = {
    "spread": [(0, 0, 10), (10, 0, 10), (-10, 0, 10), (0, 10, 10), (0, -10, 10)],
    "line": [(i * 8, 0, 10) for i in range(5)],
    "triangle": [(0, 0, 10), (6, 6, 10), (-6, 6, 10)],
}


async def deploy_swarm(
    asset_ids: list[str],
    formation: str = "spread",
    move_to_fn: Callable[[str, float, float, float], Awaitable[dict]] | None = None,
) -> dict:
    """
    Deploy multiple drones in a named formation.
    Supported formations: 'spread', 'line', 'triangle'.
    """
    positions = _FORMATIONS.get(formation, _FORMATIONS["spread"])
    move_to = move_to_fn or _runtime_grpc_client.move_to
    results = await asyncio.gather(
        *[
            move_to(aid, *positions[i % len(positions)])
            for i, aid in enumerate(asset_ids)
        ]
    )
    return {"deployed": asset_ids, "formation": formation, "results": list(results)}


async def recall_swarm(
    asset_ids: list[str],
    return_to_base_fn: Callable[[str], Awaitable[dict]] | None = None,
) -> dict:
    """Command all drones in the list to return to base immediately."""
    if return_to_base_fn is None:
        from backend.services.api.control import return_to_base as return_to_base_fn

    results = await asyncio.gather(
        *[return_to_base_fn(aid) for aid in asset_ids]
    )
    return {"recalled": asset_ids, "results": list(results)}
