import base64
import hashlib
import hmac
import os
import uuid
from collections import defaultdict
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderListResponse, OrderOut, ProductCreate, ProductOut

CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "default-secret-change-in-production")


def _encode_cursor(order_id: uuid.UUID, created_at: str, filter_params: dict[str, Any]) -> str:
    """Encode a cursor with HMAC for tamper detection."""
    data = f"{order_id}|{created_at}|{filter_params}"
    sig = hmac.new(CURSOR_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    payload = f"{order_id}|{created_at}|{sig}"
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[uuid.UUID, str, dict[str, Any]] | None:
    """Decode and verify a cursor. Returns (order_id, created_at, filter_params) or None."""
    try:
        # Add padding back
        padding = 4 - len(cursor) % 4
        if padding != 4:
            cursor += "=" * padding
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        parts = payload.split("|")
        if len(parts) != 3:
            return None
        order_id_str, created_at, sig = parts
        order_id = uuid.UUID(order_id_str)
        # Reconstruct data without sig
        data = f"{order_id_str}|{created_at}|"
        expected_sig = hmac.new(CURSOR_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        return order_id, created_at, {}
    except Exception:
        return None

app = FastAPI(title="StockFlow Mini")


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


@app.get("/orders", response_model=OrderListResponse)
def list_orders(
    limit: int = Query(ge=1, le=100),
    status: str | None = Query(default=None),
    created_from: str | None = Query(default=None),
    created_to: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrderListResponse:
    # Build filter parameters for cursor verification
    filter_params: dict[str, Any] = {}
    if status is not None:
        filter_params["status"] = status
    if created_from is not None:
        filter_params["created_from"] = created_from
    if created_to is not None:
        filter_params["created_to"] = created_to

    # Decode cursor if provided
    if cursor is not None:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            raise ApiError(400, "INVALID_CURSOR", "Cursor is invalid or tampered")
        prev_order_id, prev_created_at, prev_filter_params = decoded
        # Verify filter parameters match
        if filter_params != prev_filter_params:
            raise ApiError(400, "INVALID_CURSOR", "Cursor cannot be reused with different filters")
        # Use the cursor as the boundary: we want items AFTER this point
        # Since ordering is DESC, we need items where (created_at, id) < (prev_created_at, prev_order_id)
        cursor_created_at = prev_created_at
        cursor_order_id = prev_order_id
    else:
        cursor_created_at = None
        cursor_order_id = None

    # Build the query
    stmt = (
        select(Order)
        .where(Order.tenant_id == tenant)
        .options(selectinload(Order.items))
    )

    # Apply filters
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)

    # Apply cursor boundary
    # We want items that come BEFORE the cursor in DESC order
    # i.e., (created_at, id) < (cursor_created_at, cursor_order_id)
    if cursor_created_at is not None and cursor_order_id is not None:
        stmt = stmt.where(
            (Order.created_at, Order.id) < (cursor_created_at, cursor_order_id)
        )

    # Order by created_at DESC, id DESC
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())

    # Limit to limit + 1 to check if there's a next page
    stmt = stmt.limit(limit + 1)

    orders = session.scalars(stmt).all()

    # Determine next_cursor
    next_cursor = None
    if len(orders) > limit:
        # There's a next page
        extra = orders.pop()
        next_cursor = _encode_cursor(
            extra.id,
            extra.created_at.isoformat(),
            filter_params,
        )

    return OrderListResponse(items=orders, next_cursor=next_cursor)


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
