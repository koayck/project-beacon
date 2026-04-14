from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import backend.app as app_module


@pytest.mark.asyncio
async def test_app_lifespan_closes_adk_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    call_order: list[str] = []

    async def fake_init_db() -> None:
        call_order.append("init_db")

    async def fake_udp_start(*, on_update=None) -> None:
        assert on_update is not None
        call_order.append("udp_start")

    async def fake_restore_connections() -> None:
        call_order.append("restore_connections")

    async def fake_list_assets() -> list[object]:
        call_order.append("list_assets")
        return []

    async def fake_udp_stop() -> None:
        call_order.append("udp_stop")

    def fake_grpc_close_all() -> None:
        call_order.append("grpc_close_all")

    class FakeAutoRecallMonitor:
        def __init__(self, *args, **kwargs) -> None:
            call_order.append("auto_recall_init")

        def start(self) -> None:
            call_order.append("auto_recall_start")

        async def stop(self) -> None:
            call_order.append("auto_recall_stop")

    class FakeRunner:
        def __init__(self, *args, **kwargs) -> None:
            call_order.append("runner_init")

        async def close(self) -> None:
            call_order.append("runner_close")

    monkeypatch.setattr(app_module, "init_db", fake_init_db)
    monkeypatch.setattr(app_module.udp_listener, "start", fake_udp_start)
    monkeypatch.setattr(app_module, "restore_registered_connections", fake_restore_connections)
    monkeypatch.setattr(app_module.asset_repo, "list_all", fake_list_assets)
    monkeypatch.setattr(app_module.udp_listener, "stop", fake_udp_stop)
    monkeypatch.setattr(app_module.grpc_client, "close_all", fake_grpc_close_all)
    monkeypatch.setattr(app_module, "AutoRecallMonitor", FakeAutoRecallMonitor)
    monkeypatch.setattr(app_module, "Runner", FakeRunner)
    monkeypatch.setitem(
        sys.modules,
        "backend.agents.enhanced_commander",
        SimpleNamespace(enhanced_commander=object()),
    )

    app_module._adk_runner = None

    async with app_module.app_lifespan(app_module.app):
        assert isinstance(app_module._adk_runner, FakeRunner)

    assert app_module._adk_runner is None
    assert "runner_close" in call_order
    assert "auto_recall_start" in call_order
    assert "auto_recall_stop" in call_order
    assert call_order.index("runner_close") < call_order.index("grpc_close_all")
