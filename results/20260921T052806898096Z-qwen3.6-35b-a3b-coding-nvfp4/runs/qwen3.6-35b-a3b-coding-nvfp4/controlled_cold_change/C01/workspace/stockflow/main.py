import os
import uuid
from collections import defaultdict
from typing import Any

import hmac
import hashlib
import base64
import struct
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut, OrderListQuery, OrderListOut

app = FastAPI(title="StockFlow Mini")

CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "default-secret")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


@app.exception_handler(ApiError)
def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status, content=error_body(exc.code, exc.message, exc.details)
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body("VALIDATION_ERROR", "Invalid request", {"errors": exc.errors()}),
    )


def tenant_id(x_tenant_id: str | None = Header(default=None)) -> uuid.UUID:
    try:
        if x_tenant_id is None:
            raise ValueError
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise ApiError(400, "INVALID_TENANT", "X-Tenant-Id must be a UUID") from exc


def load_order(session: Session, tenant: uuid.UUID, order_id: uuid.UUID, lock: bool = False) -> Order:
    stmt = (
        select(Order)
         .where(Order.id == order_id, Order.tenant_id == tenant)
         .options(selectinload(Order.items))
     )
    if lock:
        stmt = stmt.with_for_update()
    order = session.scalar(stmt)
    if order is None:
        raise ApiError(404, "NOT_FOUND", "Order not found")
    return order


# Cursor encoding/decoding
def encode_cursor(order_id: uuid.UUID, created_at: datetime) -> str:
    """Encode order_id and created_at into an opaque cursor with HMAC."""
    # Pack: 16 bytes (order_id) + 8 bytes (timestamp as int)
    order_bytes = order_id.bytes
    # Use timestamp as float seconds with nanoseconds for uniqueness
    ts = created_at.timestamp()
    ts_bytes = struct.pack(">d", ts)
    payload = order_bytes + ts_bytes
    sig = hmac.new(CURSOR_SECRET.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + sig).decode()


def decode_cursor(cursor: str) -> tuple[uuid.UUID, datetime]:
    """Decode cursor and verify HMAC. Returns (order_id, created_at)."""
    try:
        raw = base64.urlsafe_b64decode(cursor)
        if len(raw) < 24:  # 16 bytes order_id + 8 bytes timestamp
            raise ValueError("cursor too short")
        payload = raw[:-32]
        sig = raw[-32:]
        expected_sig = hmac.new(CURSOR_SECRET.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("invalid signature")
        order_bytes = payload[:16]
        ts_bytes = payload[16:24]
        order_id = uuid.UUID(bytes=order_bytes)
        ts = struct.unpack(">d", ts_bytes)[0]
        created_at = datetime.fromtimestamp(ts, tz=timezone.utc)
        return order_id, created_at
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Cursor is invalid or expired") from exc


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/products", response_model=ProductOut, status_code=201)
def create_product(
    body: ProductCreate,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Product:
    product = Product(tenant_id=tenant, **body.model_dump())
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(409, "SKU_ALREADY_EXISTS", "SKU already exists") from exc
    session.refresh(product)
    return product


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Product:
    product = session.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant)
     )
    if product is None:
        raise ApiError(404, "NOT_FOUND", "Product not found")
    return product


@app.post("/orders", response_model=OrderOut, status_code=201)
def create_order(
    body: OrderCreate,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Order:
    quantities: dict[uuid.UUID, int] = defaultdict(int)
    for item in body.items:
        quantities[item.product_id] += item.quantity
    product_ids = sorted(quantities, key=str)
    try:
        products = list(
            session.scalars(
                select(Product)
                 .where(Product.id.in_(product_ids), Product.tenant_id == tenant)
                 .order_by(Product.id)
                 .with_for_update()
            )
        )
        if len(products) != len(product_ids):
            raise ApiError(404, "NOT_FOUND", "Product not found")
        for product in products:
            if product.stock < quantities[product.id]:
                raise ApiError(409, "INSUFFICIENT_STOCK", "Insufficient stock")
        order = Order(tenant_id=tenant, status="PENDING", total_amount=0)
        session.add(order)
        session.flush()
        total = 0
        for product in products:
            quantity = quantities[product.id]
            product.stock -= quantity
            line_amount = product.unit_price * quantity
            total += line_amount
            session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    unit_price=product.unit_price,
                    quantity=quantity,
                    line_amount=line_amount,
                 )
            )
        order.total_amount = total
        session.commit()
    except ApiError:
        session.rollback()
        raise
    session.expire_all()
    return load_order(session, tenant, order.id)


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Order:
    return load_order(session, tenant, order_id)


@app.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Order:
    try:
        order = load_order(session, tenant, order_id, lock=True)
        if order.status != "PENDING":
            raise ApiError(409, "INVALID_ORDER_STATE", "Order cannot be canceled")
        product_ids = sorted((item.product_id for item in order.items), key=str)
        products = {
            product.id: product
            for product in session.scalars(
                select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update()
            )
        }
        for item in order.items:
            products[item.product_id].stock += item.quantity
        order.status = "CANCELED"
        session.commit()
    except ApiError:
        session.rollback()
        raise
    session.expire_all()
    return load_order(session, tenant, order.id)


@app.get("/orders", response_model=OrderListOut)
def list_orders(
    limit: int = Query(ge=1, le=100),
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrderListOut:
    """List orders with cursor pagination.
    
    Returns orders ordered by created_at DESC, id DESC within the tenant.
    """
    # Build base query
    stmt = select(Order).where(Order.tenant_id == tenant)
    
    # Apply filters
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)
    
    # Handle cursor
    cursor_filter = None
    if cursor is not None:
        order_id, created_at = decode_cursor(cursor)
        # Cursor means "after this point" for DESC ordering
        # We need orders where (created_at, id) < (cursor_created_at, cursor_order_id)
        # For DESC order, the next page comes before the cursor
        cursor_filter = (Order.created_at, Order.id) < (created_at, order_id)
    
    # Order by created_at DESC, id DESC
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())
    
    # Apply cursor filter
    if cursor_filter is not None:
        stmt = stmt.where(cursor_filter)
    
    # Limit to limit + 1 to check if there's a next page
    stmt = stmt.limit(limit + 1)
    
    orders = session.scalars(stmt).all()
    
    # Determine if there's a next page
    has_more = len(orders) > limit
    if has_more:
        orders = orders[:limit]
    
    # Build next_cursor from the last item
    next_cursor = None
    if has_more and orders:
        last_order = orders[-1]
        next_cursor = encode_cursor(last_order.id, last_order.created_at)
    
    return OrderListOut(items=orders, next_cursor=next_cursor)
