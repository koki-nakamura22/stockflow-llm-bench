import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import hmac
import hashlib
import base64
import struct
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderOut, OrdersListQuery, OrdersListResponse, ProductCreate, ProductOut

app = FastAPI(title="StockFlow Mini")

CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "")


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


# Cursor encoding/decoding for tamper detection
def _encode_cursor(created_at: datetime, order_id: uuid.UUID) -> str:
    """Encode cursor with HMAC signature for tamper detection."""
    # Serialize: created_at (ISO string) + order_id (hex)
    data = f"{created_at.isoformat()}|{order_id.hex}"
    sig = hmac.new(CURSOR_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    payload = f"{data}|{sig}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode cursor and verify HMAC signature."""
    try:
        # Add padding if needed
        padded = cursor + "=" * (4 - len(cursor) % 4) if len(cursor) % 4 else cursor
        payload = base64.urlsafe_b64decode(padded.encode()).decode()
        # Split into data and signature
        parts = payload.rsplit("|", 1)
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        data, sig = parts
        # Verify signature
        expected_sig = hmac.new(CURSOR_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Invalid signature")
        # Parse data
        data_parts = data.split("|")
        if len(data_parts) != 2:
            raise ValueError("Invalid cursor data")
        created_at = datetime.fromisoformat(data_parts[0])
        order_id = uuid.UUID(hex=data_parts[1])
        return created_at, order_id
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Cursor is invalid or tampered") from exc


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


@app.get("/orders", response_model=OrdersListResponse)
def list_orders(
    limit: int = Query(ge=1, le=100),
    status: str | None = Query(default=None),
    created_from: str | None = Query(default=None),
    created_to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrdersListResponse:
    """List orders with cursor pagination."""
    # Build base query with tenant filter
    conditions = [Order.tenant_id == tenant]

    if status is not None:
        conditions.append(Order.status == status)

    if created_from is not None:
        try:
            dt_from = datetime.fromisoformat(created_from)
            if dt_from.tzinfo is None:
                dt_from = dt_from.replace(tzinfo=timezone.utc)
            conditions.append(Order.created_at >= dt_from)
        except ValueError:
            raise ApiError(400, "INVALID_CURSOR", "Invalid created_from format")

    if created_to is not None:
        try:
            dt_to = datetime.fromisoformat(created_to)
            if dt_to.tzinfo is None:
                dt_to = dt_to.replace(tzinfo=timezone.utc)
            conditions.append(Order.created_at <= dt_to)
        except ValueError:
            raise ApiError(400, "INVALID_CURSOR", "Invalid created_to format")

    # Build the base query
    stmt = select(Order).where(and_(*conditions)).order_by(Order.created_at.desc(), Order.id.desc())

    # If cursor is provided, decode it and apply the cursor filter
    if cursor is not None:
        created_at, order_id = _decode_cursor(cursor)
        # Cursor means: return items AFTER the cursor position
        # Since we order by created_at DESC, id DESC, "after" means:
        # (created_at < cursor_created_at) OR (created_at == cursor_created_at AND id < cursor_id)
        stmt = stmt.where(
            or_(
                Order.created_at < created_at,
                and_(Order.created_at == created_at, Order.id < order_id)
            )
        )

    # Add limit + 1 to check if there are more items
    stmt = stmt.limit(limit + 1)

    orders = session.scalars(stmt).all()

    # Determine if there's a next cursor
    next_cursor = None
    if len(orders) > limit:
        # Remove the extra item and generate cursor for the last item
        orders = orders[:limit]
        last_order = orders[-1]
        next_cursor = _encode_cursor(last_order.created_at, last_order.id)

    return OrdersListResponse(items=orders, next_cursor=next_cursor)
