import base64
import hashlib
import hmac
import json
import os
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import (
    OrderCreate,
    OrderOut,
    OrdersListOut,
    ProductCreate,
    ProductOut,
)

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


# Cursor utilities: opaque, tamper-evident using HMAC
def _encode_cursor(data: dict[str, Any]) -> str:
    """Encode cursor data with HMAC signature."""
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(
        CURSOR_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    combined = f"{payload}.{signature}"
    return base64.urlsafe_b64encode(combined.encode("utf-8")).decode("utf-8")


def _decode_cursor(token: str, expected_filters: dict[str, Any]) -> dict[str, Any]:
    """Decode and verify cursor, checking filters match."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        # Split into payload and signature
        dot_idx = raw.rfind(".")
        if dot_idx == -1:
            raise ValueError("invalid format")
        payload_str = raw[:dot_idx]
        signature = raw[dot_idx + 1 :]

        # Verify HMAC
        expected_sig = hmac.new(
            CURSOR_SECRET.encode("utf-8"),
            payload_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("signature mismatch")

        data = json.loads(payload_str)

        # Verify filters match the expected ones
        stored_filters = data.get("_filters", {})
        for key, value in expected_filters.items():
            if stored_filters.get(key) != value:
                raise ValueError("filters mismatch")

        return data
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


@app.get("/orders", response_model=OrdersListOut)
def list_orders(
    limit: int = Query(ge=1, le=100),
    status: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrdersListOut:
    # Build base query with tenant filter
    stmt = select(Order).where(Order.tenant_id == tenant)

    # Apply status filter
    if status is not None:
        stmt = stmt.where(Order.status == status)

    # Apply created_from filter
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)

    # Apply created_to filter
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)

    # Build expected filters for cursor validation
    expected_filters: dict[str, Any] = {
        "status": status,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
    }

    # Apply cursor-based pagination
    if cursor is not None:
        cursor_data = _decode_cursor(cursor, expected_filters)
        cursor_created_at = datetime.fromisoformat(cursor_data["created_at"])
        cursor_id = uuid.UUID(cursor_data["id"])
        # Find orders strictly "before" the cursor position
        # (created_at DESC, id DESC) means we want items that are less than cursor
        stmt = stmt.where(
            (Order.created_at < cursor_created_at)
            | (Order.created_at == cursor_created_at & Order.id < cursor_id)
        )

    # Order by created_at DESC, id DESC
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())

    # Fetch one extra to determine if there's a next page
    stmt = stmt.limit(limit + 1)

    orders = session.scalars(stmt).all()

    # Determine if there's a next cursor
    next_cursor: str | None = None
    if len(orders) > limit:
        orders = orders[:limit]
        last_order = orders[-1]
        next_data = {
            "created_at": last_order.created_at.isoformat(),
            "id": str(last_order.id),
            "_filters": expected_filters,
        }
        next_cursor = _encode_cursor(next_data)

    return OrdersListOut(items=orders, next_cursor=next_cursor)


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
