"""Main application entry point."""
from __future__ import annotations

import os
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from . import routers, database, schemas
from .dependencies import InvalidTenantError

app = FastAPI(title="StockFlow Mini")

# Include routers
app.include_router(routers.router)

# Health endpoint
@app.get("/health")
async def health() -> dict[str, str]:
    # Simple DB connectivity check
    try:
        with database.engine.connect() as conn:
            conn.execute("SELECT 1")
    except Exception:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "unavailable"})
    return {"status": "ok"}

# Exception handlers
@app.exception_handler(routers.APIError)
async def api_error_handler(request: Request, exc: routers.APIError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT if exc.code in {"SKU_ALREADY_EXISTS", "INSUFFICIENT_STOCK", "INVALID_ORDER_STATE"} else status.HTTP_404_NOT_FOUND,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )

@app.exception_handler(InvalidTenantError)
async def invalid_tenant_handler(request: Request, exc: InvalidTenantError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": {"code": "INVALID_TENANT", "message": exc.detail, "details": {}}},
    )

# Override validation error to match format
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Validation error", "details": exc.errors()}},
    )

# Create tables on startup
@app.on_event("startup")
async def startup():
    database.Base.metadata.create_all(bind=database.engine)
