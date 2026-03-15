"""
Thermal Agent — thermal imaging and survivor detection.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.services.drone_control import get_drone_status, scan_area

thermal_agent = Agent(
    name="thermal_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Handles thermal imaging, area scanning, and survivor detection. "
        "Use for: scanning a location for heat signatures, checking thermal feeds, "
        "and detecting survivors in disaster zones."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction="""You are a thermal imaging specialist for search and rescue drones.

When asked to scan an area:
1. Identify the target asset_id (e.g. BEACON-02)
2. Parse the centre coordinates (cx, cy, cz) and radius from the request
3. Call scan_area to initiate the thermal scan
4. Report any detected signatures or confirm the scan completed

When checking drone status before a scan:
1. Call get_drone_status first to verify the drone is operational
2. Only proceed with the scan if battery > 20%

Always report findings clearly with coordinates and confidence.
Scanning radius defaults to 5 metres unless specified.
""",
    tools=[scan_area, get_drone_status],
)
