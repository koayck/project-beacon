"""
Thermal Agent — thermal imaging and survivor detection.

REFACTORED: Now uses orchestrator for deterministic scan logic.
Agent handles reasoning and reporting only.
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.orchestrator.scanning import execute_single_building_scan, Building
from backend.services.api.control import (
    get_drone_status,
    scan_area,
    get_drone_view,
)

_DESCRIPTION = (
    "Handles thermal imaging, area scanning, and survivor detection. "
    "Use for: scanning a location for heat signatures, checking thermal feeds, "
    "and detecting survivors in disaster zones."
)

_INSTRUCTION = """You are a thermal imaging specialist for search and rescue drones.

COORDINATES: X=East, Y=Up, Z=South. Home pad at (0, 2, 0).

HYBRID ARCHITECTURE:
- For full building scans, call execute_single_building_scan() — this handles navigation,
  battery checks, and sweep scan automatically.
- For simple area scans, call scan_area() directly.
- For pre-scan sensor snapshots, call get_drone_view().

BUILDING SCAN PROCEDURE
1. Parse building information from the command (center coordinates and height).
2. Call execute_single_building_scan with building dict containing:
   - center_x: building X coordinate
   - center_z: building Z coordinate  
   - height: building height in meters
   - id: optional building identifier
3. The orchestrator handles: navigation to rooftop + 5m, battery check, sweep scan.
4. Report structured result:

SCAN COMPLETE — <asset_id>
  Building: (<center_x>, <center_z>), height <height>m
  Findings: <N> survivor(s) detected
  Battery : <pct>% remaining
  
If no survivors: "No heat signatures detected."
Survivors in flood water = CRITICAL priority.

AREA SCAN PROCEDURE (simple point scan)
1. Call get_drone_status(asset_id) to check battery > 20%.
2. Call get_drone_view(asset_id) for pre-scan sensor snapshot.
3. Call scan_area(asset_id, cx, cy, cz, radius). Default radius = 10m.
4. Report findings with distances and directions.

GATE: If shared state has nav_result with error, abort and report error.
"""


def make_thermal_agent(name: str = "thermal_agent") -> Agent:
    """
    Factory — ADK requires each agent instance to have exactly one parent.
    Call this once per parent (scan_workflow, direct use) to get separate instances.
    """
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description=_DESCRIPTION,
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="thermal_result",
        instruction=_INSTRUCTION,
        tools=[
            FunctionTool(execute_single_building_scan),
            FunctionTool(scan_area),
            FunctionTool(get_drone_status),
            FunctionTool(get_drone_view),
        ],
    )


thermal_agent = make_thermal_agent()
