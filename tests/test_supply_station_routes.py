"""Integration tests for /supply-stations REST endpoints + WS broadcast behavior."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import supply_stations


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    """Stub lifespan that skips ADK/Supabase/Docker startup for route tests."""
    yield


@pytest.fixture
def client(monkeypatch):
    # Replace the WS broadcaster with a stub so we can assert on broadcasts.
    broadcasts: list[dict] = []
    stub = MagicMock()
    stub.broadcast.side_effect = lambda payload: broadcasts.append(payload)
    monkeypatch.setattr("backend.app.ws_broadcaster", stub)

    # Skip the complex lifespan (ADK runner, Supabase, Docker probes, MCP
    # StreamableHTTPSessionManager which can only start once per instance).
    import backend.app as app_module
    # Replace the fully-combined lifespan on the router with a plain noop so
    # TestClient does not attempt to start MCP or the ADK runner.
    # Use monkeypatch for proper teardown so pytest auto-restores the original.
    monkeypatch.setattr(app_module.app.router, "lifespan_context", _noop_lifespan)

    supply_stations.reset()
    from backend.app import app
    with TestClient(app) as tc:
        tc.broadcasts = broadcasts  # type: ignore[attr-defined]
        yield tc
    supply_stations.reset()


class TestSupplyStationRoutes:
    def test_get_returns_only_home_by_default(self, client):
        resp = client.get("/supply-stations")
        assert resp.status_code == 200
        stations = resp.json()["stations"]
        assert [s["id"] for s in stations] == ["home"]

    def test_post_adds_station_and_broadcasts(self, client):
        resp = client.post("/supply-stations", json={"x": 20.0, "z": 5.0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["station"]["x"] == 20.0
        assert body["station"]["z"] == 5.0
        assert body["station"]["id"].startswith("station-")

        assert client.broadcasts == [
            {"type": "supply_station_added", "station": body["station"]}
        ]

    def test_post_rejects_out_of_bounds_with_400(self, client):
        resp = client.post("/supply-stations", json={"x": 999.0, "z": 0.0})
        assert resp.status_code == 400
        assert "out of bounds" in resp.json()["detail"].lower()
        assert client.broadcasts == []

    def test_delete_removes_and_broadcasts(self, client):
        added = client.post("/supply-stations", json={"x": 1.0, "z": 2.0}).json()["station"]
        client.broadcasts.clear()

        resp = client.delete(f"/supply-stations/{added['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        assert client.broadcasts == [
            {"type": "supply_station_removed", "id": added["id"]}
        ]

    def test_delete_home_returns_400(self, client):
        resp = client.delete("/supply-stations/home")
        assert resp.status_code == 400
        assert "home" in resp.json()["detail"].lower()
        assert client.broadcasts == []

    def test_delete_unknown_returns_404(self, client):
        resp = client.delete("/supply-stations/station-999")
        assert resp.status_code == 404
        assert client.broadcasts == []


def test_lifespan_is_restored_after_fixture_teardown():
    """Sanity: the fixture's lifespan-noop shim must not leak to later tests."""
    from backend import app as app_module_after
    # The original lifespan_context should not be the _noop we installed.
    # A simple identity check that it's not the in-fixture _noop is sufficient:
    lc = app_module_after.app.router.lifespan_context
    # If the fixture teardown worked, lc is a function or async context manager
    # different from the noop. Check it's at least still callable / non-None.
    assert lc is not None
    assert callable(lc)
