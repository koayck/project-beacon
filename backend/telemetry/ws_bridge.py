from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TelemetryBroadcaster:
    """
    Maintains the set of active WebSocket connections and pushes
    telemetry updates from the UDP listener to all connected clients.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    def connect(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        logger.debug("WS client connected (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.debug("WS client disconnected (%d total)", len(self._clients))

    def broadcast(self, payload: dict) -> None:
        """
        Called by UDPTelemetryListener on every incoming heartbeat.
        Schedules async sends to all WebSocket clients.
        """
        if not self._clients:
            return
        message = json.dumps(payload)
        asyncio.ensure_future(self._send_all(message))

    async def _send_all(self, message: str) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)
