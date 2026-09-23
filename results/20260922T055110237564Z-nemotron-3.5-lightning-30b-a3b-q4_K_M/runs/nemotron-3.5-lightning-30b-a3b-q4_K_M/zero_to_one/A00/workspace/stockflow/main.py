from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
import uuid

from stockflow.models import Base, Order, OrderItem, Product

app = FastAPI(title="StockFlow Mini")


# --- Tenant middleware ---
@app.middleware("http")
async def add_tenant_id(request: Request, call_next):
    tenant_id = request.headers.get("X-Tenant-Id")
    if not tenant_id:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_TENANT", "message": "Missing X-Tenant-Id header", "details": {}}},
        )
    # Validate UUID format
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_TENANT", "message": "Invalid X-Tenant-Id format", "details": {}}},
        )
    request.state.tenant_id = tenant_id
    response = await call_next(request)
    return response


# --- DB session dependency ---
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://stockflow:stockflow@localhost:5432/stockflow"
)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Pydantic models ---
from pydantic import BaseModel, Field, validator
from typing import List, Optional


class ProductCreate(BaseModel):
    sku: str
    name: str
    unit_price: int = Field(ge=0)
    stock: int = Field(ge=0)


class ProductResponse(BaseModel):
    id: str
    tenant_id: str
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class OrderCreateItem(BaseModel):
    product_id: str
    quantity: int = Field(ge=1)


class OrderCreate(BaseModel):
    items: List[OrderCreateItem]


class OrderResponse(BaseModel):
    id: str
    tenant_id: str
    status: str
    total_amount: int
    created_at: str
    updated_at: str
    items: List[OrderItemResponse] = []

    model_config = {"from_attributes": True}


# --- Health endpoint ---
@app.get("/health")
def health(db: Session = get_db()) -> dict[str, str]:
    try:
        db.execute(select(1))
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=500, detail="DB connection failed")


# --- Products ---
@app.post("/products", status_code=201, response_model=ProductResponse)
def create_product(body: ProductCreate, request: Request, db: Session = get_db()):
    tenant_id = request.state.tenant_id
    # Check for duplicate SKU within tenant
    existing = db.execute(
        select(Product).where(
            Product.sku == body.sku, Product.tenant_id == uuid.UUID(tenant_id)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            content={"error": {"code": "SKU_ALREADY_EXISTS", "message": "SKU already exists in this tenant", "details": {}}},
        )
    prod = Product(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        sku=body.sku,
        name=body.name,
        unit_price=body.unit_price,
        stock=body.stock,
    )
    db.add(prod)
    try:
        db.commit()
        db.refresh(prod)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            content={"error": {"code": "SKU_ALREADY_EXISTS", "message": "SKU already exists in this tenant", "details": {}}},
        )
    return prod


@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: str, request: Request, db: Session = get_db()):
    tenant_id = request.state.tenant_id
    prod = db.execute(
        select(Product).where(
            Product.id == uuid.UUID(product_id), Product.tenant_id == uuid.UUID(tenant_id)
        )
    ).scalar_one_or_none()
    if not prod:
        raise HTTPException(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
        )
    return prod


# --- Orders ---
@app.post("/orders", status_code=201, response_model=OrderResponse)
def create_order(body: OrderCreate, request: Request, db: Session = get_db()):
    tenant_id = request.state.tenant_id
    items_in = body.items

    # Group by product_id, aggregating quantities
    product_ids = [uuid.UUID(item.product_id) for item in items_in]

    # Fetch products with row-level locking for concurrency safety
    stmt = select(Product).where(
        Product.id.in_(product_ids), Product.tenant_id == uuid.UUID(tenant_id)
    )
    products = db.execute(stmt.with_for_update()).scalars().all()
    products_map = {p.id: p for p in products}

    # Check if all products exist and belong to this tenant
    requested_ids = set(product_ids)
    available_ids = set(products_map.keys())
    if requested_ids != available_ids:
        missing = requested_ids - available_ids
        if missing:
            raise HTTPException(
                status_code=404,
                content={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
            )
        raise HTTPException(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
        )

    # Check stock and compute totals
    total_amount = 0
    order_items_detail = []  # list of (product, quantity, line_amount)

    # Aggregate quantities for same product
    qty_by_product: dict = {}
    for item in items_in:
        pid = uuid.UUID(item.product_id)
        qty_by_product[pid] = qty_by_product.get(pid, 0) + item.quantity

    for pid, quantity in qty_by_product.items():
        prod = products_map[pid]
        if prod.stock < quantity:
            raise HTTPException(
                status_code=409,
                content={"error": {"code": "INSUFFICIENT_STOCK", "message": "Insufficient stock", "details": {}}},
            )
        line_amount = prod.unit_price * quantity
        total_amount += line_amount
        order_items_detail.append((prod, quantity, line_amount))

    # Create order and order items atomically
    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        tenant_id=uuid.UUID(tenant_id),
        status="PENDING",
        total_amount=total_amount,
    )
    db.add(order)

    # Snapshot product details and deduct stock
    for prod, quantity, line_amount in order_items_detail:
        item = OrderItem(
            id=uuid.uuid4(),
            order_id=order_id,
            product_id=prod.id,
            tenant_id=uuid.UUID(tenant_id),
            sku=prod.sku,
            product_name=prod.name,
            unit_price=prod.unit_price,
            quantity=quantity,
            line_amount=line_amount,
        )
        db.add(item)
        # Deduct stock atomically
        prod.stock -= quantity

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Failed to create order", "details": {}}},
        )

    # Refresh order with items
    stmt2 = select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    order_with_items = db.execute(stmt2).scalar_one()
    return order_with_items


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, request: Request, db: Session = get_db()):
    tenant_id = request.state.tenant_id
    stmt = select(Order).options(selectinload(Order.items)).where(
        Order.id == uuid.UUID(order_id), Order.tenant_id == uuid.UUID(tenant_id)
    )
    order = db.execute(stmt).scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": "Order not found", "details": {}}},
        )
    return order


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, request: Request, db: Session = get_db()):
    tenant_id = request.state.tenant_id
    stmt = select(Order).where(
        Order.id == uuid.UUID(order_id), Order.tenant_id == uuid.UUID(tenant_id)
    )
    order = db.execute(stmt).scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": "Order not found", "details": {}}},
        )

    if order.status != "PENDING":
        raise HTTPException(
            status_code=409,
            content={"error": {"code": "INVALID_ORDER_STATE", "message": "Order cannot be cancelled", "details": {}}},
        )

    # Restore stock and set status to CANCELLED atomically
    for item in order.items:
        # Find the product
        prod_stmt = select(Product).where(Product.id == item.product_id)
        prod = db.execute(prod_stmt).scalar_one()
        prod.stock += item.quantity

    order.status = "CANCELLED"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Failed to cancel order", "details": {}}},
        )

    return {"status": "cancelled"}