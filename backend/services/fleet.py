from __future__ import annotations

from backend.db.models import Asset
from backend.db.repository import asset_repo
from backend.runtime import grpc_client, udp_listener


def _grpc_target(asset_id: str) -> tuple[str, int]:
    idx = int(asset_id.upper().split("-")[1])
    return "localhost", 50050 + idx


async def restore_registered_connections() -> None:
    """Rebuild gRPC connections for assets persisted in the local database."""
    for asset in await asset_repo.list_all():
        grpc_client.register(asset.asset_id, asset.grpc_host, asset.grpc_port)


async def ensure_uplink(asset_id: str) -> dict:
    """
    Register an active drone with the commander and open its gRPC channel.
    """
    known = udp_listener.get_known_assets()
    if asset_id not in known:
        raise KeyError(f"{asset_id} not found. Run discovery first.")

    grpc_host, grpc_port = _grpc_target(asset_id)
    asset = Asset(
        asset_id=asset_id,
        asset_class="scout_quadcopter",
        grpc_host=grpc_host,
        grpc_port=grpc_port,
    )
    await asset_repo.upsert(asset)
    grpc_client.register(asset_id, grpc_host, grpc_port)
    return {
        "asset_id": asset_id,
        "grpc_host": grpc_host,
        "grpc_port": grpc_port,
        "message": f"Uplink established with {asset_id}",
    }


async def scan_frequencies() -> list[dict]:
    """Return active drones that have not yet been registered by the commander."""
    known = udp_listener.get_known_assets()
    registered = {a.asset_id for a in await asset_repo.list_all()}
    return [{**known[k], "signal_pct": 98} for k in sorted(known) if k not in registered]


async def discover_fleet(
    *,
    auto_uplink: bool = True,
    include_registered: bool = True,
) -> dict:
    """
    Return the active fleet view the agent should reason over.

    When auto_uplink=True, active drones are registered before being returned so
    follow-up control tools can act on them immediately.
    """
    known = udp_listener.get_known_assets()
    registered_assets = {asset.asset_id: asset for asset in await asset_repo.list_all()}
    fleet: list[dict] = []

    for asset_id in sorted(known):
        if auto_uplink and asset_id not in registered_assets:
            await ensure_uplink(asset_id)
            registered_assets = {asset.asset_id: asset for asset in await asset_repo.list_all()}

        registered = registered_assets.get(asset_id)
        payload = known[asset_id]
        fleet.append(
            {
                "asset_id": asset_id,
                "active": True,
                "uplinked": registered is not None,
                "battery": payload.get("battery"),
                "status": payload.get("status"),
                "x": payload.get("x"),
                "y": payload.get("y"),
                "z": payload.get("z"),
                "grpc_host": registered.grpc_host if registered else None,
                "grpc_port": registered.grpc_port if registered else None,
            }
        )

    if include_registered:
        for asset_id, registered in sorted(registered_assets.items()):
            if asset_id in known:
                continue
            fleet.append(
                {
                    "asset_id": asset_id,
                    "active": False,
                    "uplinked": True,
                    "battery": None,
                    "status": "OFFLINE",
                    "x": None,
                    "y": None,
                    "z": None,
                    "grpc_host": registered.grpc_host,
                    "grpc_port": registered.grpc_port,
                }
            )

    return {"fleet": fleet, "count": len(fleet), "active_count": len(known)}
