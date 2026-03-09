from __future__ import annotations

import asyncio
import subprocess
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.db.repository import init_db, asset_repo, mission_log_repo
from backend.db.models import Asset, MissionLog
from backend.grpc.client import DroneGrpcClient
from backend.telemetry.udp_listener import UDPTelemetryListener
from backend.telemetry.ws_bridge import TelemetryBroadcaster
from backend.licensing.routes import router as license_router

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ── Shared state ──────────────────────────────────────────────────────────────

udp_listener = UDPTelemetryListener()
ws_broadcaster = TelemetryBroadcaster()
grpc_client = DroneGrpcClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await udp_listener.start(on_update=ws_broadcaster.broadcast)
    yield
    await udp_listener.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Project Beacon", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(license_router, prefix="/license", tags=["license"])


# ── Request / Response schemas ────────────────────────────────────────────────

class SpawnRequest(BaseModel):
    asset_class: str = "scout_quadcopter"

class UplinkResponse(BaseModel):
    asset_id: str
    grpc_host: str
    grpc_port: int
    message: str

class CommandRequest(BaseModel):
    asset_id: str
    prompt: str  # natural language — routed through ADK (Phase 3)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/assets")
async def list_assets() -> list[dict]:
    """Return all registered drone assets."""
    assets = await asset_repo.list_all()
    return [a.model_dump() for a in assets]


@app.post("/spawn")
async def spawn_drone(req: SpawnRequest) -> dict:
    """
    Spin up a new simulated drone Docker container.
    The container will start broadcasting UDP heartbeats immediately.
    """
    # Count existing assets to assign the next ID
    existing = await asset_repo.list_all()
    idx = len(existing) + 1
    asset_id = f"BEACON-{idx:02d}"
    grpc_port = 50050 + idx

    try:
        subprocess.Popen(
            [
                "docker", "run", "-d", "--rm",
                "--network", "beacon-net",
                "-e", f"ASSET_ID={asset_id}",
                "-e", f"GRPC_PORT=50051",
                "-p", f"{grpc_port}:50051",
                "--name", asset_id.lower(),
                "project-beacon-drone-sim",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Docker not available")

    return {
        "asset_id": asset_id,
        "asset_class": req.asset_class,
        "grpc_port": grpc_port,
        "message": f"Spawned {asset_id}, waiting for heartbeat...",
    }


@app.post("/uplink/{asset_id}", response_model=UplinkResponse)
async def establish_uplink(asset_id: str) -> UplinkResponse:
    """
    Lock gRPC channel to a discovered drone and register it in the database.
    The drone must already be broadcasting heartbeats (detected via UDP scan).
    """
    # Check the drone is broadcasting telemetry
    known = udp_listener.get_known_assets()
    if asset_id not in known:
        raise HTTPException(
            status_code=404,
            detail=f"{asset_id} not found. Run /scan first.",
        )

    # Determine gRPC address from asset_id index
    idx = int(asset_id.split("-")[1])
    grpc_host = "localhost"
    grpc_port = 50050 + idx

    # Register in DB
    asset = Asset(
        asset_id=asset_id,
        asset_class="scout_quadcopter",
        grpc_host=grpc_host,
        grpc_port=grpc_port,
    )
    await asset_repo.upsert(asset)

    # Open gRPC channel
    grpc_client.register(asset_id, grpc_host, grpc_port)

    return UplinkResponse(
        asset_id=asset_id,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        message=f"Uplink established with {asset_id}",
    )


@app.get("/scan")
async def scan_frequencies() -> dict:
    """Return drones currently broadcasting heartbeats (not yet uplinked)."""
    known = udp_listener.get_known_assets()
    registered = {a.asset_id for a in await asset_repo.list_all()}
    unlinked = [k for k in known if k not in registered]
    return {
        "discovered": [
            {**known[k], "signal_pct": 98}
            for k in unlinked
        ]
    }


@app.post("/command")
async def send_command(req: CommandRequest) -> dict:
    """
    Send a natural language command to a drone.
    Phase 3: routes through ADK + LLM. For now, direct gRPC passthrough.
    """
    asset = await asset_repo.get(req.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"{req.asset_id} not uplinked")

    # Phase 3 placeholder — direct move for now
    result = await grpc_client.get_status(req.asset_id)

    await mission_log_repo.create(MissionLog(
        asset_id=req.asset_id,
        command="natural_language",
        params=req.prompt,
        result=str(result),
    ))

    return {"asset_id": req.asset_id, "result": result, "prompt": req.prompt}


# ── WebSocket telemetry stream ─────────────────────────────────────────────────

@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    ws_broadcaster.connect(websocket)
    try:
        while True:
            await asyncio.sleep(30)  # keep-alive; data pushed by broadcaster
    except WebSocketDisconnect:
        ws_broadcaster.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)