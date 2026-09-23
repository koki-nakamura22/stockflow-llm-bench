import base64
import hashlib
import hmac
import json
import os
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from pydantic import BaseModel

app = FastAPI(title="StockFlow Mini")

CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "default-secret-change-in-production")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


@app.exception_handler(ApiError)
def api_error_handler(_request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status, content=error_body(exc.code, exc.message, exc.details)
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(_request, exc: RequestValidationError) -> JSONResponse:
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


def encode_cursor(data: dict[str, Any]) -> str:
    """Encode cursor data into an opaque base64 string with HMAC signature."""
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(CURSOR_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    cursor_data = json.dumps({"data": data, "sig": signature}, separators=(",", ":"))
    return base64.urlsafe_b64encode(cursor_data.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, expected_filters: str) -> dict[str, Any] | None:
    """Decode and verify cursor, returning the data if valid."""
    try:
        # Add padding if needed
        padding = 4 - len(cursor) % 4
        if padding != 4:
            cursor += "=" * padding
        cursor_data = base64.urlsafe_b64decode(cursor.encode())
        decoded = json.loads(cursor_data)
        if "data" not in decoded or "sig" not in decoded:
            return None
        # Verify signature
        payload = json.dumps(decoded["data"], separators=(",", ":"), sort_keys=True)
        expected_sig = hmac.new(CURSOR_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(decoded["sig"], expected_sig):
            return None
        # Verify filters match
        if decoded["data"].get("filters") != expected_filters:
            return None
        return decoded["data"]
    except Exception:
        return None


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


class OrdersOut(BaseModel):
    """Response model for paginated orders list."""

    items: list[OrderOut]
    next_cursor: str | None = None


@app.get("/orders", response_model=OrdersOut)
def list_orders(
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
    limit: int = Query(..., ge=1, le=100),
    status: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
) -> OrdersOut:
    # Build filter hash for cursor validation
    filter_parts = []
    if status is not None:
        filter_parts.append(f"status:{status}")
    if created_from is not None:
        filter_parts.append(f"created_from:{created_from.isoformat()}")
    if created_to is not None:
        filter_parts.append(f"created_to:{created_to.isoformat()}")
    filters_hash = "|".join(filter_parts)

    # Decode cursor if provided
    cursor_data = None
    if cursor is not None:
        decoded = decode_cursor(cursor, filters_hash)
        if decoded is None:
            raise ApiError(400, "INVALID_CURSOR", "Invalid or expired cursor")
        cursor_data = decoded

    # Build query
    stmt = select(Order).where(Order.tenant_id == tenant)

    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)

    # Apply cursor filter for pagination
    # For cursor-based pagination with created_at DESC, id DESC:
    # We want: (created_at < cursor_created_at) OR (created_at == cursor_created_at AND id < cursor_id)
    if cursor_data is not None:
        cursor_created_at = datetime.fromisoformat(cursor_data["created_at"])
        cursor_id = uuid.UUID(cursor_data["id"])
        stmt = stmt.where(
            or_(
                Order.created_at < cursor_created_at,
                and_(
                    Order.created_at == cursor_created_at,
                    Order.id < cursor_id,
                ),
            )
        )

    # Order by created_at DESC, id DESC for consistent pagination
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)

    # Load items eagerly
    stmt = stmt.options(selectinload(Order.items))

    orders = session.scalars(stmt).all()

    # Determine if there are more results
    next_cursor = None
    items = list(orders[:limit])

    if len(orders) > limit:
        last_order = orders[limit - 1]
        cursor_payload = {
            "created_at": last_order.created_at.isoformat(),
            "id": str(last_order.id),
            "filters": filters_hash,
        }
        next_cursor = encode_cursor(cursor_payload)

    return OrdersOut(items=items, next_cursor=next_cursor)