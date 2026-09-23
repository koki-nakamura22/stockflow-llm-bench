import hmac
import hashlib
import base64
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import Request
from stockflow.errors import ApiError

CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "default_secret").encode("utf-8")

def encode_cursor(filters: Dict[str, Any], last_values: Dict[str, Any]) -> str:
    # Convert datetime to ISO string for JSON serialization
    payload_filters = {}
    for k, v in filters.items():
        if isinstance(v, datetime):
            payload_filters[k] = v.isoformat()
        else:
            payload_filters[k] = v

    payload_values = {}
    for k, v in last_values.items():
        if isinstance(v, datetime):
            payload_values[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            payload_values[k] = str(v)
        else:
            payload_values[k] = v

    payload = {
        "filters": payload_filters,
        "last_values": payload_values
    }
    
    payload_json = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = hmac.new(CURSOR_SECRET, payload_json, hashlib.sha256).digest()
    
    # payload_json + signature
    combined = payload_json + signature
    return base64.urlsafe_b64encode(combined).decode("utf-8")

def decode_cursor(cursor_str: str, current_filters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        combined = base64.urlsafe_b64decode(cursor_str.encode("utf-8"))
    except Exception:
        # base64.urlsafe_b64decode might fail if it's not valid base64
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor format")

    # We don't know how long the signature is, but it's SHA256 digest, so 32 bytes.
    signature_len = 32
    if len(combined) <= signature_len:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor format")
    
    payload_json = combined[:-signature_len]
    signature = combined[-signature_len:]
    
    expected_signature = hmac.new(CURSOR_SECRET, payload_json, hashlib.sha256).digest()
    
    if not hmac.compare_digest(signature, expected_signature):
        raise ApiError(400, "INVALID_CURSOR", "Cursor signature mismatch")
    
    payload = json.loads(payload_json.decode("utf-8"))
    
    # Check if filters match
    # current_filters might have None values which are not in payload['filters']
    # We should only compare non-None filters.
    
    for k, v in current_filters.items():
        if v is not None:
            # For datetime, we need to compare strings
            expected_v = v.isoformat() if isinstance(v, datetime) else v
            if payload["filters"].get(k) != expected_v:
                raise ApiError(400, "INVALID_CURSOR", "Cursor filters mismatch")
                
    # Also check if there are filters in payload that are NOT in current_filters and are NOT None in current_filters
    # But current_filters is what the user provided in the request.
    # If user provided a filter that wasn't in the cursor, it's an invalid cursor usage.
    for k, v in payload["filters"].items():
        if current_filters.get(k) is None:
             raise ApiError(400, "INVALID_CURSOR", "Cursor filters mismatch")

    return payload["last_values"]

# Actually, I need to import ApiError from main, but main imports pagination.
# This is a circular dependency.
# Let's put ApiError in a separate file or in pagination and have main import it.
# Or just define ApiError in a common place.
