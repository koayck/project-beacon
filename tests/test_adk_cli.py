"""
CLI test for the ADK commander pipeline.

Coordinate system matches the R3F / Ursina scene:
  X = right (East),  Y = up (altitude),  Z = towards viewer (South)
  Grid  : 52 × 52 units centred at origin (-26 … +26 on X and Z)
  Target building: centre (0, 0, 0), 4 floors × 3 m = 12 m tall
  Floor heights  : F1=y0  F2=y3  F3=y6  F4=y9
  Drone spawn    : (13, 1, 13) — south-east corner of grid

Run:
    uv run python tests/test_adk_cli.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Ensure project root is importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── ANSI palette ──────────────────────────────────────────────────────────────
R  = "\033[91m"   # red
G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow
B  = "\033[94m"   # blue
M  = "\033[95m"   # magenta
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
DIM = "\033[2m"
RST = "\033[0m"
BOLD = "\033[1m"

def banner(text: str) -> None:
    width = 70
    print(f"\n{B}{'━' * width}{RST}")
    print(f"{BOLD}{W}  {text}{RST}")
    print(f"{B}{'━' * width}{RST}")

def section(text: str) -> None:
    print(f"\n{C}  ▶  {BOLD}{text}{RST}")

def log_tool_call(name: str, args: dict) -> None:
    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
    print(f"  {Y}⚙  TOOL CALL{RST}  {BOLD}{name}{RST}({DIM}{args_str}{RST})")

def log_tool_resp(name: str, resp: dict) -> None:
    ok = resp.get("success", True)
    icon = f"{G}✓" if ok else f"{R}✗"
    print(f"  {icon}  RESULT    {RST} {DIM}{resp}{RST}")

def log_final(text: str) -> None:
    for line in text.strip().splitlines():
        print(f"  {G}│{RST}  {line}")

def log_elapsed(t: float) -> None:
    print(f"  {DIM}⏱  {t:.1f}s{RST}")


# ── Scene reference coords ─────────────────────────────────────────────────────
# Drone home pads (match R3F spawner positions)
BEACON_01_HOME = (13.0,  1.0,  13.0)
BEACON_02_HOME = (11.0,  1.0,  13.0)
BEACON_03_HOME = ( 9.0,  1.0,  13.0)

# Target building scan points (glass curtain-wall tower at origin)
FLOOR_H = 3.0
def scan_pt(floor: int, dx: float = 0.0, dz: float = 0.0) -> tuple:
    return (dx, (floor - 1) * FLOOR_H + 1.5, dz)

SURVIVOR_F2 = (-1.5, 3.65,  1.0)   # floor 2 thermal signature
SURVIVOR_F4 = ( 1.5, 9.65, -1.0)   # floor 4 thermal signature
ROOFTOP     = ( 0.0, 12.5,  0.0)   # top of 4-floor target building
OVERWATCH   = ( 0.0, 20.0,  0.0)   # high-altitude overwatch position


# ── ADK runner setup ──────────────────────────────────────────────────────────
async def build_runner(asset_id: str, grpc_port: int):
    from backend.tools.drone_commands import set_client
    from backend.grpc.client import DroneGrpcClient
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    client = DroneGrpcClient()
    client.register(asset_id, "localhost", grpc_port)
    set_client(client)

    from backend.agents.commander import commander
    session_service = InMemorySessionService()
    runner = Runner(agent=commander, session_service=session_service, app_name="beacon")
    return runner, session_service


async def run_command(
    runner,
    session_service,
    asset_id: str,
    prompt: str,
) -> str:
    from google.adk.sessions import InMemorySessionService
    from google.genai import types as genai_types
    import uuid

    section(f"{asset_id}  »  \"{prompt}\"")
    t0 = time.perf_counter()

    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name="beacon", user_id="gcs", session_id=session_id
    )

    full_prompt = f"Asset: {asset_id}. Command: {prompt}"
    content = genai_types.Content(
        role="user", parts=[genai_types.Part(text=full_prompt)]
    )

    final_text = ""
    async for event in runner.run_async(
        user_id="gcs", session_id=session_id, new_message=content
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                log_tool_call(part.function_call.name, dict(part.function_call.args))
            if hasattr(part, "function_response") and part.function_response:
                log_tool_resp(
                    part.function_response.name,
                    part.function_response.response or {},
                )
        if event.is_final_response():
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    final_text = part.text

    log_elapsed(time.perf_counter() - t0)
    if final_text:
        log_final(final_text)
    return final_text


# ── Test scenarios ────────────────────────────────────────────────────────────
async def main() -> None:
    banner("PROJECT BEACON — ADK Pipeline CLI Test")
    print(f"  {DIM}Scene: 52×52 grid · target building at origin · Y=up{RST}")
    print(f"  {DIM}R3F coords: X=right  Y=up  Z=towards-viewer{RST}")

    # BEACON-01 on gRPC port 50051
    runner, sessions = await build_runner("BEACON-01", 50051)

    # ── Test 1: status check ───────────────────────────────────────────────
    banner("TEST 1 · Status Check")
    await run_command(runner, sessions, "BEACON-01", "what is your current status?")

    # ── Test 2: fly to overwatch position ─────────────────────────────────
    banner("TEST 2 · Fly to High-Altitude Overwatch")
    x, y, z = OVERWATCH
    await run_command(
        runner, sessions, "BEACON-01",
        f"ascend to overwatch position at coordinates {x}, {y}, {z}"
    )

    # ── Test 3: thermal scan — floor 2 survivor location ──────────────────
    banner("TEST 3 · Thermal Scan — Floor 2 (y=3.65)")
    cx, cy, cz = SURVIVOR_F2
    await run_command(
        runner, sessions, "BEACON-01",
        f"scan for thermal signatures at coordinates {cx}, {cy}, {cz} radius 3"
    )

    # ── Test 4: fly to floor 4 survivor then scan ─────────────────────────
    banner("TEST 4 · Move to Floor 4 then Thermal Scan")
    x, y, z = SURVIVOR_F4
    await run_command(
        runner, sessions, "BEACON-01",
        f"move to {x}, {y}, {z} then scan the area for survivors with radius 3"
    )

    # ── Test 5: sweep pattern over target building rooftop ────────────────
    banner("TEST 5 · Lawnmower Sweep Over Target Building")
    await run_command(
        runner, sessions, "BEACON-01",
        "plan a sweep pattern over the area from -4,-4 to 4,4 at altitude 14, spacing 2"
    )

    # ── Test 6: return to home pad ────────────────────────────────────────
    banner("TEST 6 · Return to Base")
    await run_command(runner, sessions, "BEACON-01", "return to base")

    banner("ALL TESTS COMPLETE")
    print(f"  {G}Pipeline: NL command → ADK Commander → sub-agent → gRPC → drone sim{RST}\n")


if __name__ == "__main__":
    asyncio.run(main())
