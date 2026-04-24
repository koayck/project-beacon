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
from backend.instructions.thermal_text import THERMAL_INSTRUCTION

_DESCRIPTION = (
    "Handles thermal imaging, area scanning, and survivor detection. "
    "Use for: scanning a location for heat signatures, checking thermal feeds, "
    "and detecting survivors in disaster zones."
)

def make_thermal_agent(name: str = "thermal_agent") -> Agent:
    """
    Factory — ADK requires each agent instance to have exactly one parent.
    Call this once per parent (scan_agent, direct use) to get separate instances.
    """
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description=_DESCRIPTION,
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="thermal_result",
        instruction=THERMAL_INSTRUCTION,
        tools=[
            FunctionTool(execute_single_building_scan),
            FunctionTool(scan_area),
            FunctionTool(get_drone_status),
            FunctionTool(get_drone_view),
        ],
    )


thermal_agent = make_thermal_agent()
