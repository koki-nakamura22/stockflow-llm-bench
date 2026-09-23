"""Main application for StockFlow Mini."""
import os
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse

from .routers import products, orders
from .db import engine
from .models import Base

app = FastAPI(title="StockFlow Mini")

# Include routers
app.include_router(products.router)
app.include_router(orders.router)

# Health check
@app.get("/health")
def health() -> dict[str, str]:
    try:
        # Simple query to test DB connectivity
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error": {"code": "DB_CONNECTION", "message": str(e), "details": {}}})

# Custom exception handlers to format error responses
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # If exc.detail already dict with error key, use it
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    # Otherwise wrap
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "UNKNOWN", "message": exc.detail, "details": {}}},
    )

# Validation errors are handled by FastAPI automatically returning 422
# We override to match spec
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Validation error", "details": {"errors": exc.errors()}}},
    )

# Ensure tables exist (in case migrations not run)
Base.metadata.create_all(bind=engine)
