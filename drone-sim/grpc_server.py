from __future__ import annotations

import json
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
        s = self._sim.get_enriched_status()
        return beacon_pb2.DroneStatus(
            asset_id=s["asset_id"],
            x=s["x"],
            y=s["y"],
            z=s["z"],
            battery=s["battery"],
            status=s["status"],
            timestamp_ms=int(time.time() * 1000),
            nearby_obstacles=s["nearby_obstacles"],
            nearest_obstacle_dist=s["nearest_obstacle_dist"],
            survivors_in_range=s["survivors_in_range"],
            over_flood=s["over_flood"],
            altitude_agl=s["altitude_agl"],
        )

    def ReturnToBase(self, request, context):
        self._sim.return_to_base()
        return beacon_pb2.CommandResponse(success=True, message="Returning to base")

    def ScanArea(self, request, context):
        if request.radius < 0:
            self._sim.end_scan_mode()
            return beacon_pb2.CommandResponse(success=True, message="Scan session ended")
        self._sim.scan_area(request.cx, request.cy, request.cz)
        return beacon_pb2.CommandResponse(
            success=True,
            message=f"Scanning area at ({request.cx:.1f}, {request.cy:.1f}, {request.cz:.1f}) r={request.radius:.1f}",
        )

    def GetView(self, request, context):
        s = self._sim.get_snapshot()
        detection_range = request.range if request.range > 0 else 20.0
        view = self._sim.get_view(
            heading_deg=request.heading_deg,
            detection_range=detection_range,
        )

        objects = [
            beacon_pb2.VisibleObject(
                object_type=o["object_type"],
                object_id=o["object_id"],
                x=o["x"], y=o["y"], z=o["z"],
                distance=o["distance"],
                direction=o["direction"],
                detail=o["detail"],
            )
            for o in view["objects"]
        ]

        return beacon_pb2.ViewResponse(
            asset_id=s.asset_id,
            objects=objects,
            terrain=view["terrain"],
            altitude_agl=view["altitude_agl"],
            obstacle_ahead=view["obstacle_ahead"],
            nearest_obstacle_dist=view["nearest_obstacle_dist"],
            nearby_obstacles=view["nearby_obstacles"],
            survivors_in_range=view["survivors_in_range"],
            over_flood=view["over_flood"],
            summary=view["summary"],
        )


def serve(simulator: DroneSimulator, port: int = GRPC_PORT) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=20))
    beacon_pb2_grpc.add_DroneControlServicer_to_server(
        _DroneControlServicer(simulator), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    return server

