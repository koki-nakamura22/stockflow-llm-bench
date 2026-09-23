"""Shared dependencies and utilities."""

from __future__ import annotations

import uuid

from fastapi import Header, HTTPException, Request, status
from fastapi.requests import Request as FastAPIRequest


async def get_tenant_id(request: FastAPIRequest) -> uuid.UUID:
    """Extract and validate tenant_id from X-Tenant-Id header."""
    tenant_id_header = request.headers.get("X-Tenant-Id")
    if not tenant_id_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TENANT",
                    "message": "X-Tenant-Id header is required",
                    "details": {},
                }
            },
        )
    try:
        return uuid.UUID(tenant_id_header)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TENANT",
                    "message": "X-Tenant-Id must be a valid UUID",
                    "details": {},
                }
            },
        )
