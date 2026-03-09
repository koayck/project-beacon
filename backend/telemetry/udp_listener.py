from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

UDP_HOST = "0.0.0.0"
UDP_PORT = 5005
MAX_PACKET = 4096


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        known_assets: dict[str, dict],
        on_update: Callable[[dict], None] | None,
    ) -> None:
        self._known = known_assets
        self._on_update = on_update

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            payload = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        asset_id = payload.get("asset_id")
        if not asset_id:
            return

        self._known[asset_id] = payload
        logger.debug("heartbeat: %s", payload)

        if self._on_update:
            self._on_update(payload)

    def error_received(self, exc: Exception) -> None:
        logger.warning("UDP error: %s", exc)


class UDPTelemetryListener:
    """
    Async UDP listener that receives drone heartbeats.
    Maintains an in-memory dict of the latest state per asset_id.
    """

    def __init__(self) -> None:
        self._known_assets: dict[str, dict] = {}
        self._transport: asyncio.DatagramTransport | None = None

    async def start(
        self, on_update: Callable[[dict], None] | None = None
    ) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._known_assets, on_update),
            local_addr=(UDP_HOST, UDP_PORT),
        )
        logger.info("UDP telemetry listener on %s:%d", UDP_HOST, UDP_PORT)

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()

    def get_known_assets(self) -> dict[str, dict]:
        return dict(self._known_assets)
