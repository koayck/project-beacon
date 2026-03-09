from __future__ import annotations

import os
import sys
import time
from concurrent import futures

import grpc

# Stubs are generated into grpc_generated/ during Docker build
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "grpc_generated"))

try:
    import beacon_pb2
    import beacon_pb2_grpc
except ImportError as exc:
    raise ImportError(
        "gRPC stubs not found in grpc_generated/. "
        "Rebuild the Docker image to regenerate them."
    ) from exc

from sim import DroneSimulator

GRPC_PORT = int(os.environ.get("GRPC_PORT", "50051"))


class _DroneControlServicer(beacon_pb2_grpc.DroneControlServicer):
    def __init__(self, simulator: DroneSimulator) -> None:
        self._sim = simulator

    def MoveTo(self, request, context):
        self._sim.move_to(request.x, request.y, request.z, request.speed)
        return beacon_pb2.CommandResponse(
            success=True,
            message=f"Moving to ({request.x:.1f}, {request.y:.1f}, {request.z:.1f})",
        )

    def GetStatus(self, request, context):
        s = self._sim.get_snapshot()
        return beacon_pb2.DroneStatus(
            asset_id=s.asset_id,
            x=s.position.x,
            y=s.position.y,
            z=s.position.z,
            battery=s.battery,
            status=s.status.value,
            timestamp_ms=int(time.time() * 1000),
        )

    def ReturnToBase(self, request, context):
        self._sim.return_to_base()
        return beacon_pb2.CommandResponse(success=True, message="Returning to base")

    def ScanArea(self, request, context):
        self._sim.scan_area(request.cx, request.cy, request.cz)
        return beacon_pb2.CommandResponse(
            success=True,
            message=f"Scanning area at ({request.cx:.1f}, {request.cy:.1f}, {request.cz:.1f}) r={request.radius:.1f}",
        )


def serve(simulator: DroneSimulator, port: int = GRPC_PORT) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    beacon_pb2_grpc.add_DroneControlServicer_to_server(
        _DroneControlServicer(simulator), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    return server
