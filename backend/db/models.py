from __future__ import annotations

from datetime import datetime
from typing import Optional

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
