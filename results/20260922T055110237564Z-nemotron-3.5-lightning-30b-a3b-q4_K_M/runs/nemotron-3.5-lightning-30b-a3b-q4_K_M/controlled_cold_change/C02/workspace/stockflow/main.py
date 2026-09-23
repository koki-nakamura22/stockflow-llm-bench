import uuid
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
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


def _validate_idempotency_key(key: str | None = Header(default=None)) -> str:
    """Validate the Idempotency-Key header.
    
    - ASCII 1-128 characters, required
    - scope is tenant_id + endpoint + key
    """
    if key is None:
        raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required")
    if not isinstance(key, str):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be a string")
    if len(key) < 1 or len(key) > 128:
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be between 1 and 128 ASCII characters")
    if not all(32 <= ord(c) <= 126 for c in key):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must contain only ASCII printable characters (32-126)")
    return key


def _normalize_order_request(body: dict) -> str:
    """Normalize the order request body for idempotency key comparison.
    
    Creates a canonical representation by sorting items by product_id
    and extracting essential fields.
    """
    items = body.get("items", [])
    # Sort items by product_id for canonical representation
    sorted_items = sorted(items, key=lambda x: x.get("product_id", ""))
    # Create a normalized string representation
    item_reprs = []
    for item in sorted_items:
        product_id = item.get("product_id", "")
        quantity = item.get("quantity", 0)
        item_reprs.append(f"{product_id}:{quantity}")
    return "|".join(item_reprs)


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
    idempotency_key: str = Depends(_validate_idempotency_key),
) -> Order:
    # Normalize the request body for idempotency comparison
    normalized = _normalize_order_request(body.model_dump())

    # Check for existing idempotency key for this tenant
    result = session.execute(
        text("SELECT normalized_request, order_id FROM idempotency_keys WHERE tenant_id = :tenant AND key = :key"),
        {"tenant": str(tenant), "key": idempotency_key}
    ).first()

    if result is not None:
        existing_normalized, existing_order_id = result
        if existing_normalized == normalized:
            # Same request - return the existing order (idempotent retry)
            order = session.get(Order, existing_order_id)
            if order is not None:
                session.expire_all()
                return load_order(session, tenant, order.id)
        else:
            # Different normalized request - conflict
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key conflict: different request with same key")

    # New key - proceed with order creation
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

    # Record the idempotency key after successful order creation
    # Use INSERT ... ON CONFLICT to handle race conditions between concurrent requests
    session.execute(
        text(
            "INSERT INTO idempotency_keys (id, tenant_id, key, normalized_request, order_id, status) "
            "VALUES (:id, :tenant_id, :key, :normalized_request, :order_id, 'SUCCESS') "
            "ON CONFLICT (tenant_id, key) DO NOTHING"
        ),
        {
            "id": str(order.id),
            "tenant_id": str(tenant),
            "key": idempotency_key,
            "normalized_request": normalized,
            "order_id": str(order.id),
        }
    )
    session.commit()

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