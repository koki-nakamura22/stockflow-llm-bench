from fastapi import FastAPI

from stockflow.api import router
from stockflow.database import init_db

app = FastAPI(title="StockFlow Mini")

# Include API router
app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
async def startup() -> None:
    """Initialize database on startup."""
    init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}

