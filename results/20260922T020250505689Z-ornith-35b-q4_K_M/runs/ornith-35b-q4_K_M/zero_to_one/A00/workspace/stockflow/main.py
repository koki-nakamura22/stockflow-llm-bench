"""StockFlow Mini - Main application."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from stockflow.routers import health, orders, products

app = FastAPI(title="StockFlow Mini", version="0.1.0")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler for consistent error format."""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc.detail),
                "details": {},
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            }
        },
    )


# Include routers
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(health.router)


@app.get("/")
def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "StockFlow Mini API", "version": "0.1.0"}
