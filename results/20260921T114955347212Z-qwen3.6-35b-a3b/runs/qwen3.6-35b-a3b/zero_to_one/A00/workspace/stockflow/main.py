from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text

from stockflow.database import engine, get_db
from stockflow.models import Base
from stockflow.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown


app = FastAPI(title="StockFlow Mini", lifespan=lifespan)

app.include_router(router)


@app.get("/health")
async def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Database connection failed", "details": {}}})


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Validation error", "details": exc.errors()}},
    )
