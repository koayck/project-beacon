from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TelemetryBroadcaster:
    """
    Maintains the set of active WebSocket connections and pushes
    telemetry updates from the UDP listener to all connected clients.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        logger.debug("WS client connected (%d total)", len(self._clients))
        # Bring a newly connected client up to speed with the current
        # exploration state, so late joiners see existing fog reveals.
        await self._send_exploration_snapshot(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.debug("WS client disconnected (%d total)", len(self._clients))

    def broadcast(self, payload: dict) -> None:
        """
        Called by UDPTelemetryListener on every incoming heartbeat.
        Always updates the scout exploration tracker so sectors are
        recorded even when no WS clients are connected. Enriches scout
        payloads with exploration state and schedules fan-out to clients.
        """
        from backend.services.scout import SCOUT_ASSET_ID, exploration_tracker

        asset_id = payload.get("asset_id", "")

        if asset_id == SCOUT_ASSET_ID:
            exploration_tracker.process_heartbeat(payload)
            payload = {
                **payload,
                "explored_sectors": exploration_tracker.explored_sectors,
            }
            reveals = exploration_tracker.pop_pending_reveals()
            if reveals:
                payload["sector_reveals"] = reveals

        if not self._clients:
            return

        message = json.dumps(payload)
        asyncio.ensure_future(self._send_all(message))

    async def _send_exploration_snapshot(self, ws: WebSocket) -> None:
        """Send the current explored sector set to a newly connected client."""
        from backend.services.scout import exploration_tracker

        explored = exploration_tracker.explored_sectors
        if not explored:
            return
        snapshot = {
            "type": "exploration_snapshot",
            "asset_id": "BEACON-SCOUT",
            "explored_sectors": explored,
        }
        try:
            await ws.send_text(json.dumps(snapshot))
        except Exception:
            self.disconnect(ws)

    async def _send_all(self, message: str) -> None:
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)
