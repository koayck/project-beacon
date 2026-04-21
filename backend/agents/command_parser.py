"""
Command Parser Agent — Natural language understanding.

Parses natural language commands into structured CommandIntent.
"""
from __future__ import annotations

import re

from google.adk.agents import Agent

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.schemas import CommandIntent, MissionType
from backend.instructions.command_parser_text import (
  COMMAND_PARSER_INSTRUCTION,
)


_ASSET_PATTERN = re.compile(r"\bBEACON-[A-Z0-9-]+\b", re.IGNORECASE)
_COORDS_3D_PATTERN = re.compile(
  r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)"
)
_COORDS_2D_PATTERN = re.compile(
  r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)"
)


def _extract_asset_ids(command: str) -> list[str]:
  """Extract explicit asset identifiers from command text.

  Args:
    command: Raw natural-language command string.

  Returns:
    List of normalized asset IDs, or ["auto"] when none are present.
  """
  assets = [match.group(0).upper() for match in _ASSET_PATTERN.finditer(command)]
  return assets if assets else ["auto"]


def _extract_coordinate_target(command: str) -> list[dict]:
  """Extract coordinate targets from command text.

  Args:
    command: Raw natural-language command string.

  Returns:
    A list containing one coordinates target dict, or an empty list.
  """
  match_3d = _COORDS_3D_PATTERN.search(command)
  if match_3d:
    x_str, y_str, z_str = match_3d.groups()
    return [{
      "type": "coordinates",
      "x": float(x_str),
      "y": float(y_str),
      "z": float(z_str),
    }]

  match_2d = _COORDS_2D_PATTERN.search(command)
  if match_2d:
    x_str, z_str = match_2d.groups()
    return [{
      "type": "coordinates",
      "x": float(x_str),
      "z": float(z_str),
    }]

  return []


def parse_command(command: str) -> CommandIntent:
  """Parse natural-language mission command into a structured intent.

  Args:
    command: Natural-language operator command.

  Returns:
    Parsed CommandIntent with mission type, targets, constraints, and assets.
  """
  normalized = command.lower()
  asset_ids = _extract_asset_ids(command)
  constraints: dict[str, str] = {}

  if "urgent" in normalized or "urgently" in normalized:
    constraints["urgency"] = "high"

  # Scout recon phrasing should map to the dedicated deploy_scout_sweep path.
  if (
    "deploy scout" in normalized
    or (
      "scout" in normalized
      and ("survey" in normalized or "map" in normalized or "sector" in normalized)
    )
  ):
    constraints["operation"] = "deploy_scout_sweep"
    targets = [{"type": "area", "name": "disaster zone", "scope": "every sector"}]
    return CommandIntent(
      mission_type=MissionType.DEPLOY_SWARM,
      targets=targets,
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if "deploy" in normalized:
    targets = [{"type": "area", "name": "district"}] if "district" in normalized else []
    return CommandIntent(
      mission_type=MissionType.DEPLOY_SWARM,
      targets=targets,
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if "recall" in normalized:
    return CommandIntent(
      mission_type=MissionType.RECALL_SWARM,
      targets=[],
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if "return" in normalized and "base" in normalized:
    return CommandIntent(
      mission_type=MissionType.RETURN_HOME,
      targets=[],
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if any(token in normalized for token in ["scan", "search", "survey"]):
    targets: list[dict] = []
    if "school" in normalized:
      target = {"type": "building", "class": "school"}
      if "flooded" in normalized:
        target["context"] = "flooded"
      targets.append(target)
    if "survivor" in normalized:
      constraints["detect"] = "survivors"

    return CommandIntent(
      mission_type=MissionType.SCAN,
      targets=targets,
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if any(token in normalized for token in ["supply", "deliver"]):
    return CommandIntent(
      mission_type=MissionType.SUPPLY_DROP,
      targets=_extract_coordinate_target(command),
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if any(token in normalized for token in ["move", "navigate", "fly"]):
    return CommandIntent(
      mission_type=MissionType.MOVE,
      targets=_extract_coordinate_target(command),
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  if "patrol" in normalized:
    return CommandIntent(
      mission_type=MissionType.PATROL,
      targets=[],
      constraints=constraints,
      asset_ids=asset_ids,
      raw_command=command,
    )

  return CommandIntent(
    mission_type=MissionType.UNKNOWN,
    targets=[],
    constraints=constraints,
    asset_ids=asset_ids,
    raw_command=command,
  )

command_parser = Agent(
    name="command_parser",
    model=QWEN3_INSTRUCT,
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    description="Parses natural language commands into structured CommandIntent",
    instruction=COMMAND_PARSER_INSTRUCTION,
    tools=[],  # No tools needed, pure parsing
)
