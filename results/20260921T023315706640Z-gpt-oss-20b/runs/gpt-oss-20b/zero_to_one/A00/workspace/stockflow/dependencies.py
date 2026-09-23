"""Dependencies for tenant extraction and DB session."""
from __future__ import annotations

import uuid
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from .database import get_db

class InvalidTenantError(HTTPException):
    def __init__(self, detail: str = "Invalid tenant header"):
        super().__init__(status_code=400, detail=detail)

async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-Id")) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except Exception:
        raise InvalidTenantError()

# DB session dependency
async def get_db_session() -> Session:
    db = get_db()
    try:
        yield db
    finally:
        db.close()
