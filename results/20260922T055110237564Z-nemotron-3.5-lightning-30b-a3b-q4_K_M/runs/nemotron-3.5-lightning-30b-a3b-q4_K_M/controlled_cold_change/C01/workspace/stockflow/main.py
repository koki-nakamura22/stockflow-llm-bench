import base64
import hashlib
import hmac
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut

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


def _encode_cursor(last_created_at: Optional[float], last_id: Optional[str], filters: dict) -> str:
    """Encode a cursor value as base64url(HMAC-signed JSON payload)."""
    secret = os.environ.get("CURSOR_SECRET", "benchmark-public-secret")
    payload = {
        "lc": last_created_at,
        "li": last_id,
        "f": filters,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(payload_bytes + b"." + sig).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    """Decode and verify a cursor. Raises ValueError on invalid/tampered cursor."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "==")
    except Exception:
        raise ValueError("INVALID_CURSOR")

    if b"." not in raw:
        raise ValueError("INVALID_CURSOR")

    payload_bytes, sig_bytes = raw.rsplit(b".", 1)

    secret = os.environ.get("CURSOR_SECRET", "benchmark-public-secret")
    expected_sig = hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig_bytes, expected_sig):
        raise ValueError("INVALID_CURSOR")

    payload = json.loads(payload_bytes)

    if "lc" not in payload or "li" not in payload or "f" not in payload:
        raise ValueError("INVALID_CURSOR")

    return payload


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


@app.get("/orders")
def list_orders(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    created_from: Optional[datetime] = Query(default=None),
    created_to: Optional[datetime] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    # Build base query with tenant boundary
    stmt = select(Order).where(Order.tenant_id == tenant)

    # Build SQL WHERE clauses from filters
    sql_where: list[Any] = []
    if status is not None:
        sql_where.append(Order.status == status)
    if created_from is not None:
        cf = created_from
        if cf.tzinfo is None:
            cf = cf.replace(tzinfo=timezone.utc)
        sql_where.append(Order.created_at >= cf)
    if created_to is not None:
        ct = created_to
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        sql_where.append(Order.created_at <= ct)

    if sql_where:
        stmt = stmt.where(and_(*sql_where))

    # Cursor pagination
    if cursor is not None:
        try:
            cursor_data = _decode_cursor(cursor)
        except ValueError:
            raise ApiError(400, "INVALID_CURSOR", "Invalid or tampered cursor")

        # Verify filters match the cursor
        cursor_filters = cursor_data["f"]
        if status != cursor_filters.get("status"):
            raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")
        if created_from is not None:
            if cursor_filters.get("created_from") is None:
                raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")
            cf = created_from
            if cf.tzinfo is None:
                cf = cf.replace(tzinfo=timezone.utc)
            if cursor_filters["created_from"] != cf:
                raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")
        elif cursor_filters.get("created_from") is not None:
            raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")

        if created_to is not None:
            if cursor_filters.get("created_to") is None:
                raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")
            ct = created_to
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            if cursor_filters["created_to"] != ct:
                raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")
        elif cursor_filters.get("created_to") is not None:
            raise ApiError(400, "INVALID_CURSOR", "Cursor does not match applied filters")

        # Add position constraint for pagination
        last_created_at = cursor_data["lc"]  # float timestamp or None
        last_id_hex = cursor_data["li"]  # hex string or None

        if last_created_at is not None and last_id_hex is not None:
            last_created_at_dt = datetime.fromtimestamp(last_created_at, tz=timezone.utc)
            stmt = stmt.where(
                or_(
                    Order.created_at < last_created_at_dt,
                    and_(
                        Order.created_at == last_created_at_dt,
                        Order.id < uuid.UUID(last_id_hex),
                    ),
                )
            )
        elif last_created_at is not None:
            last_created_at_dt = datetime.fromtimestamp(last_created_at, tz=timezone.utc)
            stmt = stmt.where(Order.created_at < last_created_at_dt)
        elif last_id_hex is not None:
            # Only id available (edge case from older cursor format); paginate by id only
            stmt = stmt.where(Order.id < uuid.UUID(last_id_hex))

    # Apply limit and order
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)

    orders = session.scalars(stmt).all()

    # Determine if there's a next page (we fetched limit+1, so if len > limit, there's a next page)
    has_next = len(orders) > limit
    if has_next:
        orders = orders[:limit]  # trim to limit items

    # Build next cursor if there are more items
    next_cursor: str | None = None
    if has_next:
        last_order = orders[-1]
        filters_for_cursor: dict[str, Any] = {}
        if status is not None:
            filters_for_cursor["status"] = status
        if created_from is not None:
            filters_for_cursor["created_from"] = created_from
        if created_to is not None:
            filters_for_cursor["created_to"] = created_to
        next_cursor = _encode_cursor(
            last_created_at=last_order.created_at.replace(tzinfo=timezone.utc).timestamp(),
            last_id=str(last_order.id),
            filters=filters_for_cursor,
        )

    # Convert orders to dict format for response
    items_out: list[dict] = []
    for order in orders:
        items_out.append(
            {
                "id": order.id,
                "tenant_id": order.tenant_id,
                "status": order.status,
                "total_amount": order.total_amount,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
                "items": [
                    {
                        "id": item.id,
                        "order_id": item.order_id,
                        "product_id": item.product_id,
                        "sku": item.sku,
                        "product_name": item.product_name,
                        "unit_price": item.unit_price,
                        "quantity": item.quantity,
                        "line_amount": item.line_amount,
                    }
                    for item in order.items
                ],
            }
        )

    return {"items": items_out, "next_cursor": next_cursor}


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
