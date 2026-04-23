"""ADK CLI/Web entrypoint for Project Beacon agents.

ADK tools look for a ``root_agent`` symbol in this module.
"""

from backend.agents.commander import commander

# Canonical ADK entrypoint symbol.
root_agent = commander

# Backward-compatible alias for code paths that use `commander` naming.
commander = commander

__all__ = ["root_agent", "commander"]
