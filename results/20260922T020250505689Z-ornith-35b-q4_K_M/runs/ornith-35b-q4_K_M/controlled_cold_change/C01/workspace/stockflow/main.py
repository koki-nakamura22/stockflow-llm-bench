import base64
import hmac
import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderListResponse, OrderOut, ProductCreate, ProductOut

CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "")

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


# ---------------------------------------------------------------------------
# Cursor pagination helpers
# ---------------------------------------------------------------------------

def _cursor_encode(payload: dict[str, Any]) -> str:
    """Encode a cursor payload into an opaque, tamper-evident string.

    Format: ``<base64url(json)>.<hmac-sha256-hex>`` signed with CURSOR_SECRET.
    """
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(
        CURSOR_SECRET.encode("utf-8"),
        raw,
        "sha256",
    ).hexdigest()
    b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"{b64}.{sig}"


def _cursor_decode(token: str) -> dict[str, Any]:
    """Verify and decode a cursor. Raises ApiError on tampering / forgery."""
    parts = token.split(".")
    if len(parts) != 2:
        raise ApiError(400, "INVALID_CURSOR", "Cursor has invalid format")
    b64, sig = parts
    try:
        raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Cursor is not valid base64") from exc
    expected = hmac.new(
        CURSOR_SECRET.encode("utf-8"),
        raw,
        "sha256",
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ApiError(400, "INVALID_CURSOR", "Cursor signature verification failed")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Cursor payload is not valid json") from exc


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(400, "INVALID_CURSOR", f"Invalid datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# GET /orders  (cursor pagination)
# ---------------------------------------------------------------------------

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
    # --- cursor decoding & validation --------------------------------------
    cursor_payload: dict[str, Any] | None = None
    if cursor is not None:
        cursor_payload = _cursor_decode(cursor)
        # Filter mismatch detection: the cursor was signed with its filters
        # baked in. If the caller changed any of them the signatures won't
        # match and the cursor will be rejected.
        if cursor_payload.get("status") != status:
            raise ApiError(400, "INVALID_CURSOR", "Cursor was generated with different filters")
        if cursor_payload.get("created_from") != created_from:
            raise ApiError(400, "INVALID_CURSOR", "Cursor was generated with different filters")
        if cursor_payload.get("created_to") != created_to:
            raise ApiError(400, "INVALID_CURSOR", "Cursor was generated with different filters")
        cursor_created_at = _parse_dt(cursor_payload.get("created_at"))
        cursor_id_str: str | None = cursor_payload.get("id")
        if cursor_created_at is None or cursor_id_str is None:
            raise ApiError(400, "INVALID_CURSOR", "Cursor missing required fields")
        try:
            cursor_id = uuid.UUID(cursor_id_str)
        except ValueError as exc:
            raise ApiError(400, "INVALID_CURSOR", "Cursor id is not a valid UUID") from exc
    else:
        cursor_created_at = None
        cursor_id = None

    # --- build query -------------------------------------------------------
    stmt = (
        select(Order)
        .where(Order.tenant_id == tenant)
        .options(selectinload(Order.items))
    )

    if status is not None:
        stmt = stmt.where(Order.status == status)

    if created_from is not None:
        dt = _parse_dt(created_from)
        if dt is None:
            raise ApiError(400, "INVALID_CURSOR", f"Invalid created_from: {created_from}")
        stmt = stmt.where(Order.created_at >= dt)

    if created_to is not None:
        dt = _parse_dt(created_to)
        if dt is None:
            raise ApiError(400, "INVALID_CURSOR", f"Invalid created_to: {created_to}")
        stmt = stmt.where(Order.created_at <= dt)

    if cursor_created_at is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                Order.created_at < cursor_created_at,
                and_(Order.created_at == cursor_created_at, Order.id < cursor_id),
            )
        )

    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
    rows = list(session.scalars(stmt))

    has_extra = len(rows) > limit
    if has_extra:
        rows = rows[:limit]

    items = [OrderOut.model_validate(o) for o in rows]

    next_cursor: str | None = None
    if has_extra and rows:
        last = rows[-1]
        next_cursor = _cursor_encode(
            {
                "status": status,
                "created_from": created_from,
                "created_to": created_to,
                "created_at": last.created_at.isoformat(),
                "id": str(last.id),
            }
        )

    return OrderListResponse(items=items, next_cursor=next_cursor)


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
