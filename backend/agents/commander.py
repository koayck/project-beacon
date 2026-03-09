"""
Commander Agent — Phase 3 (ADK + Ollama)

Scaffold only. Full implementation requires:
  - Ollama running locally: `ollama serve`
  - Qwen model pulled: `ollama pull qwen2.5:4b`
  - google-adk and litellm installed

Wire into backend/app.py POST /command to replace the direct gRPC passthrough.
"""
from __future__ import annotations

# Phase 3 TODO:
# from google.adk.agents import Agent
# from google.adk.tools import FunctionTool
# from backend.tools.drone_commands import move_drone_to, return_to_base, scan_area
# from backend.tools.swarm_ops import deploy_swarm, recall_swarm
#
# commander = Agent(
#     name="commander",
#     model="ollama/qwen2.5:4b",
#     description="Routes drone swarm commands to the appropriate sub-agent.",
#     tools=[move_drone_to, return_to_base, scan_area, deploy_swarm, recall_swarm],
# )
