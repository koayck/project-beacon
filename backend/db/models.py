from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class Asset(BaseModel):
    id: Optional[int] = None
    asset_id: str
    asset_class: str = "scout_quadcopter"
    grpc_host: str
    grpc_port: int
    registered_at: Optional[str] = None


class MissionLog(BaseModel):
    id: Optional[int] = None
    asset_id: str
    command: str
    params: Optional[str] = None
    result: Optional[str] = None
    created_at: Optional[str] = None


class LicenseRecord(BaseModel):
    id: Optional[int] = None
    license_key: str
    org_name: str
    expiry_date: str     # ISO 8601: YYYY-MM-DD
    seat_count: int = 1
    activated_at: Optional[str] = None
    is_active: bool = True


class MissionRun(BaseModel):
    id: Optional[int] = None
    simulation_id: Optional[str] = None
    asset_id: str
    prompt: str
    status: Literal["success", "failed", "aborted"]
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    ttft_ms: Optional[int] = None
    tool_call_count: int = 0
    survivors_detected: int = 0
    survivors_rescued: int = 0
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    langfuse_trace_id: Optional[str] = None
    created_at: Optional[str] = None


class MissionRunEvent(BaseModel):
    id: Optional[int] = None
    run_id: int
    seq: int
    ts: str
    event_type: Literal["tool_call", "tool_result", "thinking", "text", "final", "error"]
    payload: str  # JSON-encoded blob; the API layer parses it
    created_at: Optional[str] = None
