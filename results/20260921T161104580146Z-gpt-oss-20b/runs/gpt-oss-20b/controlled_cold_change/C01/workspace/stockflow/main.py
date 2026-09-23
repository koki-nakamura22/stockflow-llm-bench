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
from stockflow.schemas import (
    OrderCreate,
    OrderOut,
    ProductCreate,
    ProductOut,
)

# ---------- Helper imports for cursor pagination ----------
import base64
import hmac
import hashlib
import json
import os
from datetime import datetime
from pydantic import BaseModel

app = FastAPI(title="StockFlow Mini")
CURSOR_SECRET = os.getenv("CURSOR_SECRET", "")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


# ---- Exception handlers ----


@app.exception_handler(ApiError)
def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Invalid request", "details": {"errors": exc.errors()}}},
    )


# ---------- Dependencies ----------

def tenant_id(x_tenant_id: str | None = Header(default=None)) -> uuid.UUID:
    try:
        if x_tenant_id is None:
            raise ValueError
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise ApiError(400, "INVALID_TENANT", "X-Tenant-Id must be a UUID") from exc


# ---------- Internal helper ----------

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


# ---------- Cursor Pagination helpers ----------

def _cursor_payload(secret: str, params: dict) -> str:
    payload_json = json.dumps(params, separators=(",", ":"), sort_keys=True)
    payload_bytes = payload_json.encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("utf-8")
    return f"{encoded_payload}.{signature}"


def _decode_cursor(secret: str, cursor: str) -> dict:
    try:
        encoded_payload, signature = cursor.rsplit(".", 1)
        payload_bytes = base64.urlsafe_b64decode(encoded_payload.encode("utf-8"))
        expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            raise ValueError("Invalid signature")
        payload_json = payload_bytes.decode("utf-8")
        return json.loads(payload_json)
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor") from exc


class OrdersResponse(BaseModel):
    items: list[OrderOut]
    next_cursor: Optional[str]


# ---------- Routes ----------

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


# -----------------------------------
# GET /orders with cursor pagination
# -----------------------------------

@app.get("/orders", response_model=OrdersResponse)
def list_orders(
    limit: int,
    status: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    cursor: Optional[str] = None,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrdersResponse:
    if limit < 1 or limit > 100:
        raise ApiError(400, "INVALID_LIMIT", "Limit must be between 1 and 100")

    # Decode cursor if provided
    last_created_at: Optional[datetime] = None
    last_id: Optional[uuid.UUID] = None
    if cursor is not None:
        cursor_payload = _decode_cursor(CURSOR_SECRET, cursor)
        # Validate filter consistency
        if cursor_payload.get("status") != (status if status is not None else None):
            raise ApiError(400, "INVALID_CURSOR", "Filter mismatch with cursor")
        if cursor_payload.get("created_from") != (created_from.isoformat() if created_from else None):
            raise ApiError(400, "INVALID_CURSOR", "Filter mismatch with cursor")
        if cursor_payload.get("created_to") != (created_to.isoformat() if created_to else None):
            raise ApiError(400, "INVALID_CURSOR", "Filter mismatch with cursor")
        if cursor_payload.get("limit") != limit:
            raise ApiError(400, "INVALID_CURSOR", "Filter mismatch with cursor")
        last_created_at_str = cursor_payload.get("last_created_at")
        last_id_str = cursor_payload.get("last_id")
        if last_created_at_str is None or last_id_str is None:
            raise ApiError(400, "INVALID_CURSOR", "Invalid cursor data")
        last_created_at = datetime.fromisoformat(last_created_at_str)
        last_id = uuid.UUID(last_id_str)

    stmt = select(Order).where(Order.tenant_id == tenant)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)
    if last_created_at is not None:
        stmt = stmt.where(
            (Order.created_at < last_created_at) |
            ((Order.created_at == last_created_at) & (Order.id < last_id))
        )
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).options(selectinload(Order.items))
    fetch_limit = limit + 1
    results = session.scalars(stmt.limit(fetch_limit)).all()
    has_more = len(results) > limit
    orders_list = results[:limit]
    next_cursor: Optional[str] = None
    if has_more and orders_list:
        last_order = orders_list[-1]
        cursor_dict = {
            "status": status,
            "created_from": created_from.isoformat() if created_from else None,
            "created_to": created_to.isoformat() if created_to else None,
            "limit": limit,
            "last_created_at": last_order.created_at.isoformat(),
            "last_id": str(last_order.id),
        }
        next_cursor = _cursor_payload(CURSOR_SECRET, cursor_dict)
    return OrdersResponse(items=orders_list, next_cursor=next_cursor)
