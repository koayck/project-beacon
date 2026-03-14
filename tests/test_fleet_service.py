from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.db.models import Asset
from backend.services import fleet


@pytest.mark.asyncio
async def test_discover_fleet_auto_uplinks_new_assets(monkeypatch: pytest.MonkeyPatch):
    upsert = AsyncMock()
    list_all = AsyncMock(side_effect=[
        [],
        [
            Asset(
                asset_id="BEACON-01",
                grpc_host="localhost",
                grpc_port=50051,
            )
        ],
    ])
    register_calls: list[tuple[str, str, int]] = []

    monkeypatch.setattr(
        fleet.udp_listener,
        "get_known_assets",
        lambda: {
            "BEACON-01": {
                "asset_id": "BEACON-01",
                "x": 1.0,
                "y": 2.0,
                "z": 3.0,
                "battery": 87.0,
                "status": "IDLE",
            }
        },
    )
    monkeypatch.setattr(fleet.asset_repo, "list_all", list_all)
    monkeypatch.setattr(fleet.asset_repo, "upsert", upsert)
    monkeypatch.setattr(
        fleet.grpc_client,
        "register",
        lambda asset_id, host, port: register_calls.append((asset_id, host, port)),
    )

    result = await fleet.discover_fleet(auto_uplink=True, include_registered=True)

    assert result["count"] == 1
    assert result["active_count"] == 1
    assert result["fleet"][0]["asset_id"] == "BEACON-01"
    assert result["fleet"][0]["uplinked"] is True
    upsert.assert_awaited_once()
    assert register_calls == [("BEACON-01", "localhost", 50051)]
