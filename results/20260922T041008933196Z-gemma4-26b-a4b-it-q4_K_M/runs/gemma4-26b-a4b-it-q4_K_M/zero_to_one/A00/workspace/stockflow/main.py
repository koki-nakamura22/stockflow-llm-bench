from fastapi import FastAPI, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from uuid import UUID
from .database import get_db, engine
from .models import Base
from .dependencies import get_tenant_id
from . import crud, schemas, exceptions

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

app = FastAPI(title="StockFlow Mini")

@app.exception_handler(exceptions.StockFlowException)
async def stockflow_exception_handler(request: Request, exc: exceptions.StockFlowException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail
    )

@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "DATABASE_ERROR", "message": "Database connection failed", "details": {}}}
        )

@app.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(
    product_data: schemas.ProductCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    return crud.create_product(db, tenant_id, product_data)

@app.get("/products/{product_id}", response_model=schemas.ProductResponse)
def get_product(
    product_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    return crud.get_product(db, tenant_id, product_id)

@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    order_create: schemas.OrderCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    return crud.create_order(db, tenant_id, order_create)

@app.get("/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order(
    order_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    return crud.get_order(db, tenant_id, order_id)

@app.post("/orders/{order_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_order(
    order_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db)
):
    return crud.cancel_order(db, tenant_id, order_id)
