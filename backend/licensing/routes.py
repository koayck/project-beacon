from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from backend.db.models import LicenseRecord
from backend.db.repository import license_repo
from backend.licensing.models import ActivateRequest, LicenseStatus
from backend.licensing.validator import validate_format, check_expiry

router = APIRouter()


@router.post("/activate", response_model=LicenseStatus)
async def activate_license(req: ActivateRequest) -> LicenseStatus:
    """
    Validate and activate a license key.
    Validation is entirely offline (format + local DB lookup).
    """
    key = req.license_key.strip().upper()

    # 1. Format + checksum check
    ok, err = validate_format(key)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    # 2. Lookup in local pre-provisioned license DB
    record = await license_repo.get_by_key(key)
    if not record:
        raise HTTPException(
            status_code=404,
            detail="License key not found. Contact your administrator.",
        )

    if not record.is_active:
        raise HTTPException(status_code=403, detail="License key has been deactivated.")

    # 3. Expiry check
    valid, days_remaining = check_expiry(record.expiry_date)
    if not valid:
        raise HTTPException(
            status_code=403,
            detail=f"License expired {abs(days_remaining)} day(s) ago.",
        )

    return LicenseStatus(
        valid=True,
        license_key=record.license_key,
        org_name=record.org_name,
        expiry_date=record.expiry_date,
        days_remaining=days_remaining,
        message="License activated successfully.",
    )


@router.get("/status", response_model=LicenseStatus)
async def license_status() -> LicenseStatus:
    """Return the status of the currently active license."""
    record = await license_repo.get_active()

    if not record:
        return LicenseStatus(valid=False, message="No license activated.")

    valid, days_remaining = check_expiry(record.expiry_date)

    return LicenseStatus(
        valid=valid,
        license_key=record.license_key,
        org_name=record.org_name,
        expiry_date=record.expiry_date,
        days_remaining=days_remaining,
        message="" if valid else f"License expired {abs(days_remaining)} day(s) ago.",
    )


@router.post("/provision")
async def provision_license(record: LicenseRecord) -> dict:
    """
    Pre-provision a license key into the local DB.
    Used by administrators during deployment (e.g. via USB import).
    """
    existing = await license_repo.get_by_key(record.license_key)
    if existing:
        raise HTTPException(status_code=409, detail="License key already exists.")

    ok, err = validate_format(record.license_key)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    await license_repo.insert(record)
    return {"message": f"License {record.license_key} provisioned for {record.org_name}"}
