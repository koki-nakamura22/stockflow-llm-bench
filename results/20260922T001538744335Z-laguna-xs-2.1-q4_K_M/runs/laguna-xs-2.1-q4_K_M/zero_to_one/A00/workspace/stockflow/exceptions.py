from __future__ import annotations

from enum import Enum

from fastapi import HTTPException


class ErrorCode(str, Enum):
    INVALID_TENANT = "INVALID_TENANT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    SKU_ALREADY_EXISTS = "SKU_ALREADY_EXISTS"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    INVALID_ORDER_STATE = "INVALID_ORDER_STATE"


class APIError(HTTPException):
    def __init__(self, status_code: int, code: ErrorCode, message: str, details: dict | None = None):
        detail = {"error": {"code": code.value, "message": message, "details": details or {}}}
        super().__init__(status_code=status_code, detail=detail)