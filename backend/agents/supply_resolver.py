"""Supply Resolver Agent.

Resolves supply commands into a canonical survivor target list and stores the
result in shared state under ``supply_targets`` for downstream supply dispatch.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._mcp import make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.instructions.supply_agent_text import SUPPLY_RESOLVER_INSTRUCTION


supply_resolver_agent = Agent(
    name="supply_resolver_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Resolves the supply target — survivors near a point or across an area — "
        "and stores the list for the supply workflow."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    output_key="supply_targets",
    instruction=SUPPLY_RESOLVER_INSTRUCTION,
    tools=[make_toolset(["find_survivors_in_area"])],
)
