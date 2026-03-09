from __future__ import annotations

from pydantic import BaseModel


class ActivateRequest(BaseModel):
    license_key: str


class LicenseStatus(BaseModel):
    valid: bool
    license_key: str | None = None
    org_name: str | None = None
    expiry_date: str | None = None
    days_remaining: int | None = None
    message: str = ""
