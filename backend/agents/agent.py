"""ADK CLI/Web entrypoint for Project Beacon agents.

ADK tools look for a ``root_agent`` symbol in this module.
"""

from backend.agents.commander import enhanced_commander

# Canonical ADK entrypoint symbol.
root_agent = enhanced_commander

# Backward-compatible alias for code paths that use `commander` naming.
commander = enhanced_commander

__all__ = ["root_agent", "commander"]
