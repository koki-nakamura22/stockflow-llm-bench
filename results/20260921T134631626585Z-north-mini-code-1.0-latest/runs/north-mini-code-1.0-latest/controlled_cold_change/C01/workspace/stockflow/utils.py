import base64
import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

CURSOR_SECRET = os.environ.get("CURSOR_SECRET")
if not CURSOR_SECRET:
    raise RuntimeError("CURSOR_SECRET environment variable must be set")

SECRET = CURSOR_SECRET.encode()
def encode_cursor(created_at: datetime, order_id: UUID, status: Optional[str], created_from: Optional[datetime], created_to: Optional[datetime], tenant_id: UUID) -> str:
    """Encode cursor with tamper detection."""
    payload = {
        "created_at": created_at.isoformat(),
        "id": str(order_id),
        "status": status,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
        "tenant_id": str(tenant_id),
    }
    payload_json = json.dumps(payload, separators=(',', ':'))
    signature = hmac.new(SECRET, payload_json.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload_json}.{signature}".encode()).decode()
    return token
def decode_cursor(token: str) -> dict:
    """Decode cursor and verify signature. Returns dict with keys: created_at, id, status, created_from, created_to, tenant_id."""
    try:
        token_bytes = base64.urlsafe_b64decode(token.encode())
        payload_json, signature = token_bytes.decode().rsplit('.', 1)
        # Verify signature
        expected_sig = hmac.new(SECRET, payload_json.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("Invalid signature")
        payload = json.loads(payload_json)
        created_at = datetime.fromisoformat(payload["created_at"])
        order_id = UUID(payload["id"])
        status = payload.get("status")
        created_from = datetime.fromisoformat(payload["created_from"]) if payload.get("created_from") else None
        created_to = datetime.fromisoformat(payload["created_to"]) if payload.get("created_to") else None
        tenant_id = UUID(payload["tenant_id"])
        return {
            "created_at": created_at,
            "id": order_id,
            "status": status,
            "created_from": created_from,
            "created_to": created_to,
            "tenant_id": tenant_id,
        }
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc
if __name__ == "__main__":
    # simple test
    pass