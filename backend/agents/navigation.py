"""
Navigation Agent — flight path planning and drone movement.

REFACTORED: Now uses orchestrator for deterministic logic.
Agent handles reasoning and operator communication only.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.orchestrator.navigation import (
    execute_navigation_sequence_tool,
    execute_return_to_base,
)
from backend.services.api.control import (
    get_drone_status,
    plan_sweep_pattern,
)
from backend.instructions.navigation_text import NAVIGATION_INSTRUCTION

_DESCRIPTION = (
    "Handles all drone movement and flight path planning. "
    "Use for: moving drones to specific coordinates, returning drones to base, "
    "checking drone status, and planning sweep patterns over an area."
)


def make_navigation_agent(name: str = "navigation_agent") -> Agent:
    """
    Factory — ADK requires each agent instance to have exactly one parent.
    Call this once per parent (commander, scan_agent) to get separate instances.
    """
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description=_DESCRIPTION,
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="nav_result",
        instruction=NAVIGATION_INSTRUCTION,
        tools=[
            execute_navigation_sequence_tool,
            execute_return_to_base,
            get_drone_status,
            plan_sweep_pattern,
        ],
    )


# Default singleton — used directly by commander for movement-only tasks
navigation_agent = make_navigation_agent()
