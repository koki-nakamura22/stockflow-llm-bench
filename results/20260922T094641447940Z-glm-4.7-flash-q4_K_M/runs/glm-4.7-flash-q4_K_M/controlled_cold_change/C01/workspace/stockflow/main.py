import base64
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
from stockflow.schemas import Cursor, OrdersResponse, OrderCreate, OrderOut, ProductCreate, ProductOut

app = FastAPI(title="StockFlow Mini")
CURSOR_SECRET = os.environ.get("CURSOR_SECRET", "benchmark-public-secret")


def encode_cursor(created_at: datetime, order_id: uuid.UUID) -> str:
    """Encode cursor with HMAC for tamper detection."""
    data = f"{created_at.isoformat()}|{order_id}".encode("utf-8")
    signature = hmac.new(CURSOR_SECRET.encode("utf-8"), data, "sha256").digest()
    combined = signature + data
    return base64.urlsafe_b64encode(combined).decode("utf-8")


def decode_cursor(cursor: str) -> Cursor:
    """Decode cursor and verify HMAC."""
    try:
        combined = base64.urlsafe_b64decode(cursor.encode("utf-8"))
        if len(combined) < 32:
            raise ValueError("Invalid cursor format")
        signature = combined[:32]
        data = combined[32:]
        expected_signature = hmac.new(CURSOR_SECRET.encode("utf-8"), data, "sha256").digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Invalid cursor signature")
        created_at_str, order_id_str = data.decode("utf-8").split("|")
        return Cursor(created_at=datetime.fromisoformat(created_at_str), id=uuid.UUID(order_id_str))
    except Exception as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor") from exc


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


@app.get("/orders", response_model=OrdersResponse)
def list_orders(
    status: str | None = Query(None),
    created_from: datetime | None = Query(None),
    created_to: datetime | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(..., ge=1, le=100),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrdersResponse:
    """List orders with cursor pagination."""
    # Build base query with tenant filter
    stmt = select(Order).where(Order.tenant_id == tenant)

    # Apply optional filters
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)

    # Order by created_at DESC, id DESC
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())

    # Handle cursor pagination
    if cursor is not None:
        cursor_data = decode_cursor(cursor)
        # Filter must match cursor's tenant (already handled) and time boundaries if specified
        # If a time boundary filter was provided, it must match the cursor's time
        if created_from is not None and cursor_data.created_at < created_from:
            raise ApiError(400, "INVALID_CURSOR", "Cursor is outside the specified time range")
        if created_to is not None and cursor_data.created_at > created_to:
            raise ApiError(400, "INVALID_CURSOR", "Cursor is outside the specified time range")
        # Find the position after the cursor record
        stmt = stmt.where(
            (Order.created_at < cursor_data.created_at) | (
                (Order.created_at == cursor_data.created_at) & (Order.id < cursor_data.id)
            )
        )

    # Apply limit
    stmt = stmt.limit(limit)

    # Execute query
    orders = session.execute(stmt).scalars().all()

    # Build response
    items = [load_order(session, tenant, order.id) for order in orders]
    next_cursor = None

    if orders:
        last_order = orders[-1]
        next_cursor = encode_cursor(last_order.created_at, last_order.id)

    return OrdersResponse(items=items, next_cursor=next_cursor)
