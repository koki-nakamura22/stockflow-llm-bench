"""Dependencies for StockFlow Mini."""
import uuid
from fastapi import Header, HTTPException, status

from .schemas import ErrorDetail

TENANT_HEADER = "X-Tenant-Id"

async def get_tenant_id(tenant_id: str = Header(..., alias=TENANT_HEADER)) -> uuid.UUID:
    try:
        return uuid.UUID(tenant_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "INVALID_TENANT", "message": "Invalid tenant ID", "details": {}}},
        )
