"""
Recovery Agent — Adaptive error handling.

Analyzes mission failures and proposes recovery strategies.
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.schemas import (
    ErrorContext,
    RecoveryPlan,
    RecoveryAction,
)
from backend.services.api.control import list_all_drones, get_drone_status
from backend.instructions.recovery_text import RECOVERY_INSTRUCTION


recovery_agent = Agent(
    name="recovery_agent",
    model=QWEN3_INSTRUCT,
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    description="Recovery specialist for drone mission failures",
   instruction=RECOVERY_INSTRUCTION,
    output_schema=RecoveryPlan,
    tools=[
        FunctionTool(list_all_drones),
        FunctionTool(get_drone_status),
    ],
)
