import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, status, Depends
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker, Session

from stockflow.models import Base, Product, Order, OrderItem
from stockflow.schemas import (
    ProductCreateRequest,
    ProductResponse,
    OrderCreateRequest,
    OrderResponse,
)
from stockflow.crud import generate_uuid

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables if they don't exist (development convenience)
Base.metadata.create_all(bind=engine)

# Dependency to get a DB session per request

def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Custom error response helper

def http_error(code: str, message: str, status_code: int = 400, details=None):
    if details is None:
        details = {}
    raise HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": details}},
    )

app = FastAPI(title="StockFlow Mini")

# Helper: extract tenant ID from header and validate
def extract_tenant_id(X_Tenant_Id: str = Header(..., description="Tenant UUID")):
    try:
        return uuid.UUID(X_Tenant_Id)
    except ValueError:
        http_error("INVALID_TENANT", "Invalid X-Tenant-Id header", status.HTTP_400_BAD_REQUEST)

# Product endpoints

@app.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: ProductCreateRequest,
    tenant_id: uuid.UUID = Depends(extract_tenant_id),
    db: Session = Depends(get_db),
):
    # Check for duplicate SKU within tenant
    stmt = select(Product).where(Product.tenant_id == tenant_id, Product.sku == request.sku)
    existing = db.scalar(stmt)
    if existing:
        http_error("SKU_ALREADY_EXISTS", f"SKU '{request.sku}' already exists for this tenant", status.HTTP_409_CONFLICT)

    # Create product
    product = Product(
        id=generate_uuid(),
        tenant_id=tenant_id,
        sku=request.sku,
        name=request.name,
        unit_price=request.unit_price,
        stock=request.stock,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(product)
    db.flush()
    return ProductResponse.from_orm(product)

@app.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(extract_tenant_id),
    db: Session = Depends(get_db),
):
    stmt = select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    product = db.scalar(stmt)
    if not product:
        http_error("NOT_FOUND", "Product not found", status.HTTP_404_NOT_FOUND)
    return ProductResponse.from_orm(product)

# Order endpoints

@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    request: OrderCreateRequest,
    tenant_id: uuid.UUID = Depends(extract_tenant_id),
    db: Session = Depends(get_db),
):
    # Aggregate items by product_id
    items_by_product = {}
    for item in request.items:
        items_by_product[item.product_id] = items_by_product.get(item.product_id, 0) + item.quantity

    # Lock products belonging to tenant for update
    product_ids = list(items_by_product.keys())
    stmt = select(Product).where(Product.id.in_(product_ids), Product.tenant_id == tenant_id).with_for_update()
    products = db.scalars(stmt).all()

    product_map = {p.id: p for p in products}

    # Validate all products exist and belong to tenant
    for pid in product_ids:
        if pid not in product_map:
            http_error("NOT_FOUND", f"Product {pid} not found or does not belong to tenant", status.HTTP_404_NOT_FOUND)

    # Validate stock
    for pid, qty_needed in items_by_product.items():
        prod = product_map[pid]
        if prod.stock < qty_needed:
            http_error("INSUFFICIENT_STOCK", f"Insufficient stock for product {pid}", status.HTTP_409_CONFLICT)

    # Decrement stocks
    for pid, qty_needed in items_by_product.items():
        prod = product_map[pid]
        prod.stock -= qty_needed
        prod.updated_at = datetime.now(timezone.utc)
        db.add(prod)

    # Create order
    order = Order(
        id=generate_uuid(),
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(order)
    db.flush()

    # Create order items with snapshots
    total_amount = 0
    for pid, qty in items_by_product.items():
        prod = product_map[pid]
        line_amount = prod.unit_price * qty
        total_amount += line_amount
        order_item = OrderItem(
            id=generate_uuid(),
            order_id=order.id,
            product_id=pid,
            sku=prod.sku,
            product_name=prod.name,
            unit_price=prod.unit_price,
            quantity=qty,
            line_amount=line_amount,
        )
        db.add(order_item)

    # Update order total_amount
    order.total_amount = total_amount
    order.updated_at = datetime.now(timezone.utc)
    db.add(order)

    # Reload order with items
    db.refresh(order, attribute_names=["items"])
    return OrderResponse.from_orm(order)

@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(extract_tenant_id),
    db: Session = Depends(get_db),
):
    stmt = select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    order = db.scalar(stmt)
    if not order:
        http_error("NOT_FOUND", "Order not found", status.HTTP_404_NOT_FOUND)

    # Load items if not already loaded
    if not order.items:
        stmt_items = select(OrderItem).where(OrderItem.order_id == order_id)
        order.items = db.scalars(stmt_items).all()
    return OrderResponse.from_orm(order)

@app.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(extract_tenant_id),
    db: Session = Depends(get_db),
):
    # Lock the order row
    stmt = select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    order = db.scalar(stmt)
    if not order:
        http_error("NOT_FOUND", "Order not found", status.HTTP_404_NOT_FOUND)

    if order.status != "PENDING":
        http_error("INVALID_ORDER_STATE", "Only pending orders can be cancelled", status.HTTP_409_CONFLICT)

    # Load order items
    stmt_items = select(OrderItem).where(OrderItem.order_id == order_id)
    items = db.scalars(stmt_items).all()

    # Restore stock for each product (ensure tenant matches via product)
    for item in items:
        prod_stmt = select(Product).where(Product.id == item.product_id, Product.tenant_id == tenant_id).with_for_update()
        prod = db.scalar(prod_stmt)
        if prod:
            prod.stock += item.quantity
            prod.updated_at = datetime.now(timezone.utc)
            db.add(prod)

    # Update order status to cancelled
    order.status = "CANCELLED"
    order.updated_at = datetime.now(timezone.utc)
    db.add(order)

    return {"status": "cancelled"}

@app.get("/health")
def health(db: Session = Depends(get_db)):
    # Simple DB ping
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        # According to spec, health endpoint returns 200 only if DB reachable.
        # We'll treat DB error as internal error.
        http_error("INTERNAL_ERROR", "Database connection failed", status.HTTP_503_SERVICE_UNAVAILABLE)