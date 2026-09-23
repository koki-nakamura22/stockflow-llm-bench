"""StockFlow Mini - FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from stockflow.routers import router
from stockflow.schemas import ErrorResponse, ErrorDetail

app = FastAPI(title="StockFlow Mini")

app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message=str(exc.detail),
                details={},
            )
        ).model_dump(),
    )
