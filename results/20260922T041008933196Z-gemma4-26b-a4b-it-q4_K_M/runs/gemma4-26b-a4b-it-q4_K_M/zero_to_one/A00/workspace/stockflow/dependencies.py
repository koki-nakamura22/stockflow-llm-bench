from fastapi import Request, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from .database import SessionLocal
from .exceptions import InvalidTenantException

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_tenant_id(request: Request) -> UUID:
    tenant_id_str = request.headers.get("X-Tenant-Id")
    if not tenant_id_str:
        raise InvalidTenantException()
    try:
        return UUID(tenant_id_str)
    except ValueError:
        raise InvalidTenantException()
