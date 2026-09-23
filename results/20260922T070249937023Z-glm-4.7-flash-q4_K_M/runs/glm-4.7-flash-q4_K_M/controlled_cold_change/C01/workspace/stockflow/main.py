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
from sqlalchemy import and_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product

app = FastAPI(title="StockFlow Mini")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "")


def encode_cursor(payload: Any) -> str:
    """Encode cursor payload with signature."""
    payload_json = payload.model_dump_json()
    signature = hmac.new(
        CURSOR_SECRET.encode(),
        payload_json.encode(),
        hashlib.sha256,
    ).hexdigest()
    combined = f"{signature}:{payload_json}"
    return base64.urlsafe_b64encode(combined.encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Decode and verify cursor payload."""
    try:
        data = base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor format")

    if ":" not in data:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor format")

    signature, payload_json = data.split(":", 1)
    
    expected_signature = hmac.new(
        CURSOR_SECRET.encode(),
        payload_json.encode(),
        hashlib.sha256,
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_signature):
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor signature")

    return json.loads(payload_json)


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


@app.get("/orders", response_model=OrderListResponse)
def list_orders(
    limit: int = Query(..., ge=1, le=100, description="Number of items per page"),
    status: str | None = Query(None, description="Filter by order status"),
    created_from: datetime | None = Query(None, description="Filter by created date (inclusive)"),
    created_to: datetime | None = Query(None, description="Filter by created date (inclusive)"),
    cursor: str | None = Query(None, description="Pagination cursor"),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrderListResponse:
    """List orders with cursor-based pagination."""
    # Build base query with tenant filter
    stmt = select(Order).where(Order.tenant_id == tenant)
    
    # Apply status filter if provided
    if status:
        stmt = stmt.where(Order.status == status)
    
    # Apply date range filter if provided
    if created_from:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Order.created_at <= created_to)
    
    # Get cursor payload if provided
    cursor_payload = None
    if cursor:
        try:
            cursor_payload = decode_cursor(cursor)
            # Verify cursor is for the same tenant
            stmt = stmt.where(
                and_(
                    Order.created_at < cursor_payload["created_at"],
                    Order.id < cursor_payload["id"],
                )
            )
        except ApiError:
            raise ApiError(400, "INVALID_CURSOR", "Invalid cursor")
    
    # Execute query with pagination and ordering
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
    
    orders = session.scalars(stmt).all()
    
    # Determine next cursor
    next_cursor = None
    if len(orders) > limit:
        next_cursor = encode_cursor({
            "created_at": orders[limit].created_at,
            "id": orders[limit].id,
        })
        orders = orders[:limit]
    
    # Load items for each order
    result_items = []
    for order in orders:
        session.expire(order)
        session.refresh(order)
        result_items.append(load_order(session, tenant, order.id))
    
    return OrderListResponse(items=result_items, next_cursor=next_cursor)
