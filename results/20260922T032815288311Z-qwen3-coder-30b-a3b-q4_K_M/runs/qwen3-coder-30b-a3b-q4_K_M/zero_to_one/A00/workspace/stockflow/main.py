from fastapi import FastAPI, Depends, HTTPException, status, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
from .database import engine, Base, get_db
from .models import Product, Order
from .schemas import (
    ProductCreate, 
    ProductResponse, 
    OrderCreate, 
    OrderResponse,
    HealthResponse
)
from .crud import (
    create_product, 
    get_product, 
    get_all_products,
    create_order,
    get_order,
    cancel_order,
    get_product_by_sku
)
from .exceptions import (
    InvalidTenantException, 
    ProductNotFoundException, 
    SKUAlreadyExistsException,
    InsufficientStockException,
    InvalidOrderStateException,
    OrderNotFoundException
)

app = FastAPI(title="StockFlow Mini")

# Create tables
Base.metadata.create_all(bind=engine)

@app.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    try:
        db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=500, detail="Database connection failed")

@app.post("/products", status_code=status.HTTP_201_CREATED, response_model=ProductResponse)
def create_product_endpoint(
    product: ProductCreate,
    tenant_id: str = Depends(lambda: None),  # Will be validated in middleware
    db: Session = Depends(get_db)
):
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    
    try:
        return create_product(db, product, tenant_id)
    except SKUAlreadyExistsException as e:
        raise HTTPException(status_code=409, detail=e.message)

@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product_endpoint(
    product_id: UUID,
    tenant_id: str = Depends(lambda: None),
    db: Session = Depends(get_db)
):
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    
    try:
        return get_product(db, product_id, tenant_id)
    except ProductNotFoundException as e:
        raise HTTPException(status_code=404, detail=e.message)

@app.post("/orders", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
def create_order_endpoint(
    order: OrderCreate,
    tenant_id: str = Depends(lambda: None),
    db: Session = Depends(get_db)
):
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    
    try:
        return create_order(db, order, tenant_id)
    except ProductNotFoundException as e:
        raise HTTPException(status_code=404, detail=e.message)
    except InsufficientStockException as e:
        raise HTTPException(status_code=409, detail=e.message)

@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_endpoint(
    order_id: UUID,
    tenant_id: str = Depends(lambda: None),
    db: Session = Depends(get_db)
):
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    
    try:
        return get_order(db, order_id, tenant_id)
    except OrderNotFoundException as e:
        raise HTTPException(status_code=404, detail=e.message)

@app.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order_endpoint(
    order_id: UUID,
    tenant_id: str = Depends(lambda: None),
    db: Session = Depends(get_db)
):
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    
    try:
        return cancel_order(db, order_id, tenant_id)
    except OrderNotFoundException as e:
        raise HTTPException(status_code=404, detail=e.message)
    except InvalidOrderStateException as e:
        raise HTTPException(status_code=409, detail=e.message)

# Error handlers
@app.exception_handler(InvalidTenantException)
async def invalid_tenant_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )

@app.exception_handler(ProductNotFoundException)
async def product_not_found_exception_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )

@app.exception_handler(OrderNotFoundException)
async def order_not_found_exception_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )

@app.exception_handler(SKUAlreadyExistsException)
async def sku_already_exists_exception_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )

@app.exception_handler(InsufficientStockException)
async def insufficient_stock_exception_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )

@app.exception_handler(InvalidOrderStateException)
async def invalid_order_state_exception_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    )