"""Scan Resolver Agent.

Resolves scan commands into canonical building target lists and stores the result
in shared state under ``scan_buildings`` for downstream scan orchestration.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._mcp import make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.instructions.scan_workflow_text import SCAN_RESOLVER_INSTRUCTION


scan_resolver_agent = Agent(
    name="scan_resolver_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Resolves the scan target — a single building or all buildings in an area — "
        "and stores the list for the scan workflow."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    output_key="scan_buildings",
    instruction=SCAN_RESOLVER_INSTRUCTION,
    tools=[make_toolset(["resolve_scan_target", "find_buildings_in_area"])],
)
