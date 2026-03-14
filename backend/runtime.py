from __future__ import annotations

from backend.grpc.client import DroneGrpcClient
from backend.telemetry.udp_listener import UDPTelemetryListener
from backend.telemetry.ws_bridge import TelemetryBroadcaster

# Shared runtime singletons for the commander node.
udp_listener = UDPTelemetryListener()
ws_broadcaster = TelemetryBroadcaster()
grpc_client = DroneGrpcClient()
