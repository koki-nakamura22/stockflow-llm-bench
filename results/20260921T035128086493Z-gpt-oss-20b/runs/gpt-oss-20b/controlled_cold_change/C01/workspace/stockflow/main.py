import uuid
from collections import defaultdict
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut

import os
import hmac
import hashlib
import base64
import json
from datetime import datetime

app = FastAPI(title="StockFlow Mini")
CURSOR_SECRET = os.getenv("CURSOR_SECRET", "default-secret")


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


# Cursor utilities

def _encode_cursor(
    created_at: datetime,
    order_id: uuid.UUID,
    status: Optional[str],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
) -> str:
    payload = {
        "created_at": created_at.isoformat(),
        "order_id": str(order_id),
        "status": status,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
    }
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode()
    signature = hmac.new(CURSOR_SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest().encode()
    token = base64.urlsafe_b64encode(payload_bytes + b"." + signature).decode()
    return token


def _decode_cursor(token: str) -> dict:
    try:
        decoded = base64.urlsafe_b64decode(token.encode())
        payload_bytes, signature = decoded.rsplit(b".", 1)
        expected_sig = hmac.new(CURSOR_SECRET.encode(), payload_bytes, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("Invalid signature")
        payload = json.loads(payload_bytes.decode())
        # Convert datetime strings back
        payload["created_at"] = datetime.fromisoformat(payload["created_at"]) if payload["created_at"] else None
        payload["created_from"] = datetime.fromisoformat(payload["created_from"]) if payload["created_from"] else None
        payload["created_to"] = datetime.fromisoformat(payload["created_to"]) if payload["created_to"] else None
        payload["order_id"] = uuid.UUID(payload["order_id"]) if payload["order_id"] else None
        return payload
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor") from exc


# Helper to build filter conditions

def _apply_filters(stmt, tenant: uuid.UUID, status: Optional[str], created_from: Optional[datetime], created_to: Optional[datetime]):
    stmt = stmt.where(Order.tenant_id == tenant)
    if status:
        stmt = stmt.where(Order.status == status)
    if created_from:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Order.created_at <= created_to)
    return stmt


# Helper to apply cursor pagination

def _apply_cursor(stmt, cursor_data: dict):
    created_at = cursor_data["created_at"]
    order_id = cursor_data["order_id"]
    # For DESC order, we need rows where (created_at, id) < (cursor_created_at, cursor_id)
    stmt = stmt.where(
        (Order.created_at < created_at) |
        ((Order.created_at == created_at) & (Order.id < order_id))
    )
    return stmt


# Load order helper

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


# New endpoint: GET /orders with cursor pagination
@app.get("/orders")
def list_orders(
    limit: int,
    status: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    cursor: Optional[str] = None,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
):
    # Validate limit
    if limit < 1 or limit > 100:
        raise ApiError(400, "INVALID_LIMIT", "limit must be between 1 and 100")

    # Base query
    stmt = select(Order).options(selectinload(Order.items))
    stmt = _apply_filters(stmt, tenant, status, created_from, created_to)
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())

    # Handle cursor
    if cursor:
        cursor_data = _decode_cursor(cursor)
        # Ensure filter consistency
        if cursor_data["status"] != status or cursor_data["created_from"] != created_from or cursor_data["created_to"] != created_to:
            raise ApiError(400, "INVALID_CURSOR", "Cursor does not match filters")
        stmt = _apply_cursor(stmt, cursor_data)

    # Fetch limit+1 to determine next page
    stmt = stmt.limit(limit + 1)
    orders = session.scalars(stmt).all()

    items = [OrderOut.model_validate(order, from_attributes=True) for order in orders[:limit]]
    next_cursor = None
    if len(orders) > limit:
        last_order = orders[limit - 1]
        next_cursor = _encode_cursor(
            created_at=last_order.created_at,
            order_id=last_order.id,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )

    return {"items": items, "next_cursor": next_cursor}

