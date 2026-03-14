"""
Scan Workflow — SequentialAgent that navigates then scans.

Replaces the two-phase natural-language instruction in the commander with a
deterministic ADK pipeline: navigation_agent runs first (moves drone to target,
stores result in state["nav_result"]), then thermal_agent scans at that location.
Thermal phase is gated: if nav_result contains an error, thermal reports abort and
does not execute scan_area.

This offloads multi-step sequencing from the 4B model to the ADK framework.
"""
from __future__ import annotations

from google.adk.agents import SequentialAgent

from backend.agents.navigation import make_navigation_agent
from backend.agents.thermal import make_thermal_agent

# Separate instance — ADK enforces single-parent ownership per agent object
_nav_for_scan = make_navigation_agent(name="navigation_agent_scan", scan_mode=True)
_thermal_for_scan = make_thermal_agent(name="thermal_agent_scan")

scan_workflow = SequentialAgent(
    name="scan_workflow",
    description=(
        "Navigate a drone to a target location then scan it for heat signatures. "
        "Use for any 'scan building/area/location' command. "
        "Do NOT use for movement-only commands — use navigation_agent directly instead."
    ),
    sub_agents=[_nav_for_scan, _thermal_for_scan],
)
