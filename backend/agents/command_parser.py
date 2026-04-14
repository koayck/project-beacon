"""
Command Parser Agent — Natural language understanding.

Parses natural language commands into structured CommandIntent.
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.schemas import CommandIntent, MissionType


_INSTRUCTION = """You are a command parser for drone Ground Control Station.

Your job: Parse natural language commands into structured CommandIntent JSON.

MISSION TYPES:
- move: Navigate drone to coordinates or location
- scan: Thermal scan for survivors, heat signatures
- supply_drop: Deliver supplies to survivors or location
- return_home: Return drone to base
- deploy_swarm: Deploy all drones in formation
- recall_swarm: Return all drones to base
- patrol: Patrol an area continuously
- unknown: Cannot determine mission type

TARGET TYPES:
- coordinates: Explicit (x, y, z) or (x, z) coordinates
- building: Building reference (school, hospital, apartment, house)
- area: Area reference (district, neighborhood, zone)
- survivor: Survivor ID or reference

PARSING RULES:
1. Extract mission_type from verb (move/navigate/fly → move, scan/search → scan)
2. Extract targets with type and coordinates/description
3. Extract constraints (urgency, priority, battery limits)
4. Extract asset_ids from explicit mentions (BEACON-01, BEACON-02)
5. Default asset_ids to ["auto"] if not specified

EXAMPLES:

Input: "Move BEACON-01 to coordinates (10, -5)"
Output: {
  "mission_type": "move",
  "targets": [{"type": "coordinates", "x": 10.0, "z": -5.0}],
  "constraints": {},
  "asset_ids": ["BEACON-01"],
  "raw_command": "Move BEACON-01 to coordinates (10, -5)"
}

Input: "Scan the flooded school for survivors"
Output: {
  "mission_type": "scan",
  "targets": [{"type": "building", "class": "school", "context": "flooded"}],
  "constraints": {"detect": "survivors", "priority": "submerged"},
  "asset_ids": ["auto"],
  "raw_command": "Scan the flooded school for survivors"
}

Input: "Deploy all drones to scan the district"
Output: {
  "mission_type": "deploy_swarm",
  "targets": [{"type": "area", "name": "district", "scope": "entire"}],
  "constraints": {"urgency": "high"},
  "asset_ids": ["auto"],
  "raw_command": "Deploy all drones to scan the district"
}

Input: "Return BEACON-02 to base"
Output: {
  "mission_type": "return_home",
  "targets": [],
  "constraints": {},
  "asset_ids": ["BEACON-02"],
  "raw_command": "Return BEACON-02 to base"
}

Input: "Send supplies to the survivors at building (-15, -20)"
Output: {
  "mission_type": "supply_drop",
  "targets": [{"type": "building", "x": -15.0, "z": -20.0, "recipients": "survivors"}],
  "constraints": {},
  "asset_ids": ["auto"],
  "raw_command": "Send supplies to the survivors at building (-15, -20)"
}

HANDLING AMBIGUITY:
- If coordinates unclear, mark type="building" or "area" with description
- If mission unclear, use mission_type="unknown"
- Default to asset_ids=["auto"] when not specified
- Preserve original command in raw_command

OUTPUT FORMAT:
Return CommandIntent JSON matching the schema. Be concise.
"""


def parse_command(user_command: str) -> CommandIntent:
    """
    Parse natural language command (placeholder for non-agent mode).
    
    This is a fallback function. In practice, the agent handles parsing.
    """
    # Simple regex-based parsing for offline mode
    import re
    
    cmd_lower = user_command.lower()
    
    # Extract mission type (order matters for multi-intent phrases)
    mission_type = MissionType.UNKNOWN
    if any(word in cmd_lower for word in ["deploy"]):
        mission_type = MissionType.DEPLOY_SWARM
    elif any(word in cmd_lower for word in ["move", "navigate", "fly", "go"]):
        mission_type = MissionType.MOVE
    elif any(word in cmd_lower for word in ["scan", "search", "find"]):
        mission_type = MissionType.SCAN
    elif any(word in cmd_lower for word in ["supply", "deliver", "drop"]):
        mission_type = MissionType.SUPPLY_DROP
    elif any(word in cmd_lower for word in ["return", "recall", "come back"]):
        if "all" in cmd_lower or "swarm" in cmd_lower:
            mission_type = MissionType.RECALL_SWARM
        else:
            mission_type = MissionType.RETURN_HOME
    
    # Extract coordinates
    coord_pattern = r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*(?:,\s*(-?\d+(?:\.\d+)?))?\s*\)?"
    coords = re.findall(coord_pattern, user_command)
    
    targets = []
    if coords:
        # Two-value form is interpreted as (x, z). Three-value form is (x, y, z).
        first, second, third = coords[0]
        target = {"type": "coordinates", "x": float(first)}
        if third:
            target["y"] = float(second)
            target["z"] = float(third)
        else:
            target["z"] = float(second)
        targets.append(target)
    else:
        # Basic fallback target extraction for offline mode.
        if any(word in cmd_lower for word in ["school", "hospital", "apartment", "house", "building"]):
            building_class = next(
                (word for word in ["school", "hospital", "apartment", "house"] if word in cmd_lower),
                "building",
            )
            target: dict[str, object] = {"type": "building", "class": building_class}
            if "flooded" in cmd_lower:
                target["context"] = "flooded"
            targets.append(target)
        elif any(word in cmd_lower for word in ["district", "neighborhood", "zone", "area"]):
            area_name = next(
                (word for word in ["district", "neighborhood", "zone", "area"] if word in cmd_lower),
                "area",
            )
            targets.append({"type": "area", "name": area_name})
    
    # Extract asset IDs
    asset_pattern = r"BEACON-(\d+)"
    asset_matches = re.findall(asset_pattern, user_command, re.IGNORECASE)
    asset_ids = [f"BEACON-{num}" for num in asset_matches] if asset_matches else ["auto"]

    constraints = {}
    if "urgent" in cmd_lower or "immediately" in cmd_lower:
        constraints["urgency"] = "high"
    if "survivor" in cmd_lower:
        constraints["detect"] = "survivors"
    
    return CommandIntent(
        mission_type=mission_type,
        targets=targets,
        constraints=constraints,
        asset_ids=asset_ids,
        raw_command=user_command
    )


command_parser = Agent(
    name="command_parser",
    model=QWEN3_INSTRUCT,
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    description="Parses natural language commands into structured CommandIntent",
    instruction=_INSTRUCTION + "\n\nOUTPUT: Return valid CommandIntent JSON only, no explanation.",
    tools=[],  # No tools needed, pure parsing
)
