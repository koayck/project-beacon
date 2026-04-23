"""Integration tests for /supply-stations REST endpoints + WS broadcast behavior."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import supply_stations
from backend import app as _app_module_at_import

# Capture the original lifespan at module import time, before any fixture runs.
_ORIGINAL_LIFESPAN_CONTEXT = _app_module_at_import.app.router.lifespan_context


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
    def test_get_returns_empty_by_default(self, client):
        """Home is not a supply station — registry starts empty."""
        resp = client.get("/supply-stations")
        assert resp.status_code == 200
        assert resp.json()["stations"] == []

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

    def test_delete_home_returns_404(self, client):
        """Home is no longer a station at all — DELETE falls through to not-found."""
        resp = client.delete("/supply-stations/home")
        assert resp.status_code == 404
        assert client.broadcasts == []

    def test_post_over_station_limit_returns_429(self, client, monkeypatch):
        """Hitting MAX_USER_STATIONS returns 429 and does not broadcast."""
        monkeypatch.setattr(supply_stations, "MAX_USER_STATIONS", 1)
        # First station succeeds.
        first = client.post("/supply-stations", json={"x": 1.0, "z": 1.0})
        assert first.status_code == 200
        client.broadcasts.clear()

        resp = client.post("/supply-stations", json={"x": 2.0, "z": 2.0})
        assert resp.status_code == 429
        assert "limit" in resp.json()["detail"].lower()
        assert client.broadcasts == []

    def test_delete_unknown_returns_404(self, client):
        resp = client.delete("/supply-stations/station-999")
        assert resp.status_code == 404
        assert client.broadcasts == []

    def test_world_switch_resets_registry_and_broadcasts(self, client, monkeypatch):
        """Switching worlds wipes user-placed stations and emits a reset event.

        Stations placed in one world may fall inside buildings in another,
        so the registry is cleared on world switch. Clients re-hydrate via GET.
        """
        # Stub the world-loading / scout side-effects that /world/{id} touches
        # so the test runs without a real world model swap.
        monkeypatch.setattr("backend.world.model.load_world", lambda _wid: None)
        monkeypatch.setattr("backend.services.scout.cancel_scout_sweep", lambda: False)

        class _StubTracker:
            def reset(self) -> None:
                pass

        monkeypatch.setattr("backend.services.scout.exploration_tracker", _StubTracker())

        # Also stub the gRPC client so the route doesn't try to reach drones.
        class _StubClient:
            def registered_asset_ids(self) -> list[str]:
                return []

        monkeypatch.setattr("backend.app.grpc_client", _StubClient())

        # Place a user station, then trigger the world switch.
        added = client.post("/supply-stations", json={"x": 1.0, "z": 2.0}).json()["station"]
        assert added["id"] != "home"
        client.broadcasts.clear()

        resp = client.post("/world/1")
        assert resp.status_code == 200

        # Registry is empty post-reset (home was never a supply station).
        get_resp = client.get("/supply-stations")
        assert get_resp.json()["stations"] == []

        # A reset broadcast fired.
        assert {"type": "supply_stations_reset"} in client.broadcasts


def test_lifespan_is_restored_after_fixture_teardown(client):
    """Sanity: the fixture's lifespan-noop shim must not leak to later tests.

    Uses the client fixture so monkeypatch teardown fires at function end.
    Inside the test body, the fixture has installed the noop lifespan.
    We assert that the noop is currently active and different from the original.
    """
    from backend import app as app_module_now

    # During the test (fixture active) this should be the noop:
    assert app_module_now.app.router.lifespan_context is not _ORIGINAL_LIFESPAN_CONTEXT


def test_lifespan_identity_after_other_fixture_tests():
    """Runs AFTER the fixture tests; must see the original lifespan restored.

    This test runs after test_lifespan_is_restored_after_fixture_teardown,
    confirming that monkeypatch teardown has restored the original lifespan.
    """
    from backend import app as app_module_now

    assert app_module_now.app.router.lifespan_context is _ORIGINAL_LIFESPAN_CONTEXT
