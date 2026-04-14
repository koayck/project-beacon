"""
Enhanced Commander Agent — Hybrid architecture with strategic planning.

Routes commands through: Command Parser → Mission Planner → Orchestrators
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.command_parser import command_parser
from backend.agents.mission_planner import mission_planner
from backend.agents.recovery import recovery_agent
from backend.agents.navigation import navigation_agent
from backend.agents.scan_workflow import scan_workflow
from backend.agents.supply_workflow import supply_workflow
from backend.agents.schemas import CommandIntent


def is_complex_mission(intent: dict) -> bool:
    return CommandIntent.model_validate(intent).is_complex_mission()


_INSTRUCTION = """You are the Ground Control Station commander for autonomous drone swarms.

HYBRID ARCHITECTURE:
Your workflow follows a 3-stage pattern:
1. Parse → 2. Plan (if complex) → 3. Execute

STAGE 1: PARSE COMMAND
- Delegate to command_parser agent to get CommandIntent
- CommandIntent contains: mission_type, targets, constraints, asset_ids

STAGE 2: PLAN MISSION (if complex)
- Use intent.is_complex_mission() to decide if planning needed
- Complex: Multiple targets, auto assignment, or urgency constraints
- If complex: Delegate to mission_planner agent to get MissionPlan
- If simple: Skip to execution

STAGE 3: EXECUTE
Route to specialist based on mission_type:
- move: Call navigation_agent with target coordinates
- scan: Call thermal_agent or scan_workflow for building scans
- return_home: Call navigation_agent's return_to_base
- supply_drop: Call supply_workflow

ERROR RECOVERY:
If execution fails with unrecoverable error:
- Call recovery_agent with error context
- Execute recovery plan (retry, swap drone, abort, etc.)

EXAMPLES:

Simple Command: "Move BEACON-01 to (10, -5)"
→ Parse: CommandIntent(mission_type=move, targets=[{x:10, z:-5}], asset_ids=["BEACON-01"])
→ Plan: Skip (simple, single drone)
→ Execute: navigation_agent.execute_navigation_sequence("BEACON-01", 10, -5)

Complex Command: "Scan all flooded buildings for survivors"
→ Parse: CommandIntent(mission_type=scan, targets=[{type:area}], asset_ids=["auto"])
→ Plan: mission_planner → MissionPlan(strategy=parallel_sweep, assignments=...)
→ Execute: thermal_agent for each assigned building in parallel

Failed Mission: Navigation blocked, battery 35%, backup available
→ Recovery: recovery_agent → RecoveryPlan(action=swap_drone, ...)
→ Execute: Retry with BEACON-03

GUIDELINES:
- Always parse command first (no guessing)
- Plan only when is_complex_mission() returns True
- Execute using orchestrators (fast, deterministic)
- Recover using recovery_agent (adaptive)
- Report results clearly to operator

Keep responses concise and operational.
"""


enhanced_commander = Agent(
    name="enhanced_commander",
    model=QWEN3_INSTRUCT,
    description="Enhanced commander with strategic planning and adaptive recovery",
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    instruction=_INSTRUCTION,
    sub_agents=[
        command_parser,
        mission_planner,
        recovery_agent,
        navigation_agent,
        scan_workflow,
        supply_workflow,
    ],
    tools=[
        FunctionTool(is_complex_mission)
    ],
)
