"""
Intent and Plan schemas for hybrid agent architecture.

These Pydantic models define the structured data exchanged between agents.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MissionType(str, Enum):
    """Type of mission to execute."""
    MOVE = "move"
    SCAN = "scan"
    SUPPLY_DROP = "supply_drop"
    RETURN_HOME = "return_home"
    DEPLOY_SWARM = "deploy_swarm"
    RECALL_SWARM = "recall_swarm"
    PATROL = "patrol"
    UNKNOWN = "unknown"


class TargetType(str, Enum):
    """Type of target in a mission."""
    COORDINATES = "coordinates"
    BUILDING = "building"
    AREA = "area"
    SURVIVOR = "survivor"


class MissionStrategy(str, Enum):
    """Execution strategy for multi-drone missions."""
    SINGLE_DRONE = "single_drone"
    PARALLEL_SWEEP = "parallel_sweep"
    SEQUENTIAL_RELAY = "sequential_relay"
    HUB_SPOKE = "hub_spoke"


class CommandIntent(BaseModel):
    """
    Structured intent parsed from natural language command.
    
    Output of Command Parser Agent.
    """
    mission_type: MissionType
    targets: list[dict] = Field(default_factory=list)
    constraints: dict = Field(default_factory=dict)
    asset_ids: list[str] = Field(default_factory=lambda: ["auto"])
    raw_command: str = ""
    
    def is_complex_mission(self) -> bool:
        """Determine if mission planner needed."""
        return (
            len(self.targets) > 1 or
            self.asset_ids == ["auto"] or
            "urgency" in self.constraints or
            self.mission_type in [MissionType.DEPLOY_SWARM, MissionType.PATROL]
        )


class FleetAssignment(BaseModel):
    """Assignment of drone to target."""
    asset_id: str
    target_id: str
    reason: str = ""


class MissionPlan(BaseModel):
    """
    Strategic execution plan for a mission.
    
    Output of Mission Planner Agent.
    """
    mission_type: MissionType
    strategy: MissionStrategy
    fleet_assignments: list[FleetAssignment] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    contingencies: dict[str, str] = Field(default_factory=dict)
    estimated_duration_min: float = 0.0
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ErrorContext(BaseModel):
    """
    Context for error recovery.
    
    Input to Recovery Agent.
    """
    error_type: str
    asset_id: str
    mission_plan: Optional[MissionPlan] = None
    current_state: dict = Field(default_factory=dict)
    partial_results: Optional[dict] = None
    attempt_count: int = 0


class RecoveryAction(str, Enum):
    """Recovery action to take."""
    ABORT = "abort"
    RETRY = "retry"
    SWAP_DRONE = "swap_drone"
    ALTITUDE_OVERRIDE = "altitude_override"
    PARTIAL_COMPLETION = "partial_completion"
    MANUAL_INTERVENTION = "manual_intervention"


class RecoveryPlan(BaseModel):
    """
    Recovery strategy for mission failure.
    
    Output of Recovery Agent.
    """
    action: RecoveryAction
    modified_plan: Optional[MissionPlan] = None
    rationale: str = ""
    estimated_success_probability: float = Field(default=0.5, ge=0.0, le=1.0)
