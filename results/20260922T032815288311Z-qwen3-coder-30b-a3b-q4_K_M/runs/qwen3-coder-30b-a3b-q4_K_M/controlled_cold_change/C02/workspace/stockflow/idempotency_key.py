import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from stockflow.models import IdempotencyKey


def create_idempotency_key(
    session: Session,
    tenant_id: uuid.UUID,
    endpoint: str,
    key: str,
    request_body: dict[str, Any],
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    """Create an idempotency key record."""
    # Hash the request body for comparison
    request_hash = hashlib.sha256(
        json.dumps(request_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    
    # Create the idempotency key record
    idempotency_key = IdempotencyKey(
        tenant_id=tenant_id,
        endpoint=endpoint,
        key=key,
        request_hash=request_hash,
        response_status=response_status,
        response_body=json.dumps(response_body, separators=(",", ":")),
    )
    session.add(idempotency_key)
    session.flush()


def get_idempotency_key(
    session: Session,
    tenant_id: uuid.UUID,
    endpoint: str,
    key: str,
) -> IdempotencyKey | None:
    """Get an idempotency key record."""
    return session.scalar(
        IdempotencyKey.__table__.select().where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.key == key,
        )
    )


def validate_idempotency_key(
    session: Session,
    tenant_id: uuid.UUID,
    endpoint: str,
    key: str,
    request_body: dict[str, Any],
) -> tuple[int, dict[str, Any]] | None:
    """Validate idempotency key and return stored response if exists."""
    # Hash the current request body
    request_hash = hashlib.sha256(
        json.dumps(request_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    
    # Check if this key already exists
    existing_key = get_idempotency_key(session, tenant_id, endpoint, key)
    if not existing_key:
        return None  # No previous request with this key
    
    # If the request hash matches, return the stored response
    if existing_key.request_hash == request_hash:
        response_body = json.loads(existing_key.response_body)
        return (existing_key.response_status, response_body)
    
    # Request hash does not match - conflict
    return (409, {"error": {"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key conflict"}})