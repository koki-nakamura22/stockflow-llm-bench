from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from typing import List, Generator
import uuid

from sqlalchemy import text
from stockflow.database import Base, engine, SessionLocal, Product, Order, OrderItem
from datetime import datetime

app = FastAPI(title="StockFlow Mini")

# -----------------------------
# Dependency for DB session
# -----------------------------

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# Tenant header validation
# -----------------------------

def get_tenant_id(request: Request) -> uuid.UUID:
    tenant_header = request.headers.get("X-Tenant-Id")
    if not tenant_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TENANT",
                    "message": "Missing or invalid X-Tenant-Id header.",
                    "details": {},
                }
            },
        )
    try:
        tenant_id = uuid.UUID(tenant_header)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "INVALID_TENANT", "message": "Invalid tenant ID.", "details": {}}},
        )
    return tenant_id

# -----------------------------
# Error handlers
# -----------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    message = exc.detail.get("error", {}).get("message", "") if isinstance(exc.detail, dict) else exc.detail
    code = exc.detail.get("error", {}).get("code", "") if isinstance(exc.detail, dict) else ""
    error = {
        "error": {"code": code or "ERROR", "message": message or str(exc.detail), "details": {}}
    }
    return JSONResponse(status_code=exc.status_code, content=error)


# -----------------------------
# Health endpoint
# -----------------------------

@app.get("/health")
async def health(db: SessionLocal = Depends(get_db)) -> dict[str, str]:
    # Simple DB check
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=500, content={"status": "fail"})
    return {"status": "ok"}


# -----------------------------
# Pydantic schemas
# -----------------------------

from pydantic import BaseModel, Field

class ProductCreateRequest(BaseModel):
    sku: str
    name: str
    unit_price: int
    stock: int

class ProductResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int

class OrderCreateRequest(BaseModel):
    items: List[OrderItemCreate]

class OrderItemResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID | None
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class OrderResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]

    class Config:
        orm_mode = True

# -----------------------------
# Product endpoints
# -----------------------------

@app.post("/products", status_code=status.HTTP_201_CREATED, response_model=ProductResponse)
def create_product(
    product_req: ProductCreateRequest,
    db: SessionLocal = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    # check duplicate SKU within tenant
    existing = (
        db.query(Product)
        .filter_by(tenant_id=tenant_id, sku=product_req.sku)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "SKU_ALREADY_EXISTS", "message": "Duplicate SKU.", "details": {}}},
        )
    new_product = Product(
        tenant_id=tenant_id,
        sku=product_req.sku,
        name=product_req.name,
        unit_price=product_req.unit_price,
        stock=product_req.stock,
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product

@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: uuid.UUID,
    db: SessionLocal = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    prod = db.query(Product).filter_by(id=product_id, tenant_id=tenant_id).first()
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Product not found.", "details": {}}},
        )
    return prod

# -----------------------------
# Order endpoints
# -----------------------------

@app.post("/orders", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
def create_order(
    order_req: OrderCreateRequest,
    db: SessionLocal = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    # Merge same product
    merged: dict[uuid.UUID, int] = {}
    for item in order_req.items:
        merged[item.product_id] = merged.get(item.product_id, 0) + item.quantity
    # Load products and lock rows for update
    products = (
        db.query(Product)
        .filter(Product.id.in_(merged.keys()), Product.tenant_id == tenant_id)
        .with_for_update()
        .all()
    )
    if len(products) != len(merged):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "One or more products not found.", "details": {}}},
        )
    # Check stock
    for prod in products:
        if prod.stock < merged[prod.id]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": {"code": "INSUFFICIENT_STOCK", "message": f"Insufficient stock for SKU {prod.sku}.", "details": {}}},
            )
    # All good, calculate total and create order
    total = 0
    order = Order(tenant_id=tenant_id, status="PENDING", total_amount=0)
    db.add(order)
    db.flush()  # get order.id
    order_items = []
    for prod in products:
        qty = merged[prod.id]
        line_amount = prod.unit_price * qty
        total += line_amount
        order_item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            sku=prod.sku,
            product_name=prod.name,
            unit_price=prod.unit_price,
            quantity=qty,
            line_amount=line_amount,
        )
        order_items.append(order_item)
        # decrement stock
        prod.stock -= qty
        db.add(order_item)
    order.total_amount = total
    db.commit()
    db.refresh(order)
    return order

@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: uuid.UUID,
    db: SessionLocal = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    order = db.query(Order).filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Order not found.", "details": {}}},
        )
    return order

@app.post("/orders/{order_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_order(
    order_id: uuid.UUID,
    db: SessionLocal = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    order = db.query(Order).filter_by(id=order_id, tenant_id=tenant_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Order not found.", "details": {}}},
        )
    if order.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "INVALID_ORDER_STATE", "message": "Order cannot be cancelled.", "details": {}}},
        )
    # restore stock
    for item in order.items:
        prod = db.query(Product).filter_by(id=item.product_id, tenant_id=tenant_id).with_for_update().first()
        if prod:
            prod.stock += item.quantity
    order.status = "CANCELLED"
    db.commit()
    return {"id": str(order.id), "status": order.status}

# -----------------------------
# Create tables on startup
# -----------------------------

@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
