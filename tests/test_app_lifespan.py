from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

import backend.app as app_module


@pytest.mark.asyncio
async def test_app_lifespan_closes_adk_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    call_order: list[str] = []
    session_create_calls: list[tuple[str, str, str]] = []

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
        class _SessionService:
            async def create_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
                call_order.append("session_create")
                session_create_calls.append((app_name, user_id, session_id))

        def __init__(self, *args, **kwargs) -> None:
            call_order.append("runner_init")
            self.session_service = self._SessionService()

        async def close(self) -> None:
            call_order.append("runner_close")

    monkeypatch.setattr(app_module, "init_db", fake_init_db)
    monkeypatch.setattr(
        app_module,
        "_ADK_SESSION_DB_URL",
        "postgresql+asyncpg://test-user:test-pass@localhost:5432/test-db",
    )
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
    assert "session_create" in call_order
    assert session_create_calls == [
        (
            app_module._ADK_APP_NAME,
            app_module._ADK_USER_ID,
            app_module._ADK_SHARED_SESSION_ID,
        )
    ]
    assert "auto_recall_start" in call_order
    assert "auto_recall_stop" in call_order
    assert call_order.index("runner_close") < call_order.index("grpc_close_all")


@pytest.mark.asyncio
async def test_ensure_adk_shared_session_is_idempotent() -> None:
    calls: list[tuple[str, str, str]] = []

    class FakeAlreadyExistsError(Exception):
        """Raised by session service when a session already exists."""

    class FakeSessionService:
        async def create_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
            calls.append((app_name, user_id, session_id))
            if len(calls) > 1:
                raise FakeAlreadyExistsError("Session already exists")

    runner: Any = SimpleNamespace(session_service=FakeSessionService())
    original_exc = app_module.AlreadyExistsError
    app_module.AlreadyExistsError = FakeAlreadyExistsError

    try:
        first = await app_module._ensure_adk_shared_session(runner)
        second = await app_module._ensure_adk_shared_session(runner)
    finally:
        app_module.AlreadyExistsError = original_exc

    assert first == app_module._ADK_SHARED_SESSION_ID
    assert second == app_module._ADK_SHARED_SESSION_ID
    assert calls == [
        (
            app_module._ADK_APP_NAME,
            app_module._ADK_USER_ID,
            app_module._ADK_SHARED_SESSION_ID,
        ),
        (
            app_module._ADK_APP_NAME,
            app_module._ADK_USER_ID,
            app_module._ADK_SHARED_SESSION_ID,
        ),
    ]
