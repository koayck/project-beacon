"""
Command Parser Agent — Natural language understanding.

Parses natural language commands into structured CommandIntent.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.instructions.command_parser_text import (
  COMMAND_PARSER_INSTRUCTION,
)

command_parser = Agent(
    name="command_parser",
    model=QWEN3_INSTRUCT,
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    description="Parses natural language commands into structured CommandIntent",
    instruction=COMMAND_PARSER_INSTRUCTION,
    tools=[],  # No tools needed, pure parsing
)
