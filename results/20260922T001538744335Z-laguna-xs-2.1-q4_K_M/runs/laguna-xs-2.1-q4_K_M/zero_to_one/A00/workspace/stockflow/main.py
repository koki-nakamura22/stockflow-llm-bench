from __future__ import annotations

from fastapi import FastAPI

from stockflow.db import engine
from stockflow.routes import router

app = FastAPI(title="StockFlow Mini")


@app.on_event("startup")
async def startup_event() -> None:
    # Test DB connectivity at startup
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
    except Exception as e:
        raise RuntimeError(f"Database connection failed: {e}")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)