from __future__ import annotations

import os
import signal
import time

from grpc_server import serve
from sim import DroneSimulator
from telemetry import start_telemetry

ASSET_ID = os.environ.get("ASSET_ID", "BEACON-01")
GRPC_PORT = int(os.environ.get("GRPC_PORT", "50051"))


def main() -> None:
    print(f"[{ASSET_ID}] Starting drone simulation")

    sim = DroneSimulator(asset_id=ASSET_ID)
    sim.start()

    grpc_server = serve(sim, port=GRPC_PORT)
    print(f"[{ASSET_ID}] gRPC server on :{GRPC_PORT}")

    start_telemetry(sim)
    print(f"[{ASSET_ID}] Ready")

    def _shutdown(signum, frame):
        print(f"[{ASSET_ID}] Shutting down...")
        sim.stop()
        grpc_server.stop(grace=2)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _shutdown(None, None)


if __name__ == "__main__":
    main()
