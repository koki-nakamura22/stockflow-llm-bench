import json
import re
import uuid
from collections import defaultdict
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import (
    IdempotencyKey,
    Order,
    OrderItem,
    Product,
)
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut

app = FastAPI(title="StockFlow Mini")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message,
                       "details": details or {}}}


@app.exception_handler(ApiError)
def api_error_handler(
    _request: Request, exc: ApiError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=error_body(exc.code, exc.message, exc.details),
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            "VALIDATION_ERROR", "Invalid request", {"errors": exc.errors()}
        ),
    )


def tenant_id(
    x_tenant_id: str | None = Header(default=None),
) -> uuid.UUID:
    try:
        if x_tenant_id is None:
            raise ValueError
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise ApiError(
            400, "INVALID_TENANT", "X-Tenant-Id must be a UUID"
        ) from exc


def load_order(
    session: Session,
    tenant: uuid.UUID,
    order_id: uuid.UUID,
    lock: bool = False,
) -> Order:
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


def normalize_order_body(body: OrderCreate) -> str:
    """Normalize the order body for comparison."""
    items_sorted = sorted(
        [(item.product_id, item.quantity) for item in body.items],
        key=lambda x: str(x[0]),
    )
    return json.dumps(items_sorted, sort_keys=True)


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
        raise ApiError(
            409, "SKU_ALREADY_EXISTS", "SKU already exists"
        ) from exc
    session.refresh(product)
    return product


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Product:
    product = session.scalar(
        select(Product).where(
            Product.id == product_id, Product.tenant_id == tenant
        )
    )
    if product is None:
        raise ApiError(404, "NOT_FOUND", "Product not found")
    return product


@app.post(
    "/orders",
    response_model=OrderOut,
    status_code=201,
)
def create_order(
    body: OrderCreate,
    tenant: uuid.UUID = Depends(tenant_id),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key"
    ),
    session: Session = Depends(get_session),
) -> Order:
    # Validate idempotency key
    if idempotency_key is None:
        raise ApiError(
            400,
            "MISSING_IDEMPOTENCY_KEY",
            "Idempotency-Key header is required",
        )
    if len(idempotency_key) < 1 or len(idempotency_key) > 128:
        raise ApiError(
            400,
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key must be 1-128 ASCII characters",
        )
    if not re.fullmatch(r"[\x20-\x7E]+", idempotency_key):
        raise ApiError(
            400,
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key must be ASCII characters only",
        )

    # Scope: tenant_id + endpoint + key
    scope = f"{tenant}/POST /orders"
    normalized_body = normalize_order_body(body)

    # Try to acquire a lock on the idempotency key row
    # Using SELECT ... FOR UPDATE to handle concurrent requests
    stmt = (
        select(IdempotencyKey)
        .where(
            IdempotencyKey.tenant_id == tenant,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == idempotency_key,
        )
        .with_for_update()
    )
    existing = session.scalar(stmt)

    if existing is not None:
        if existing.status == "SUCCESS":
            # Return cached response
            cached = json.loads(existing.response_body)
            return cached
        # If there's a non-success record, it means a conflict
        # This shouldn't happen with our design, but handle it
        raise ApiError(
            409,
            "IDEMPOTENCY_CONFLICT",
            "Request body does not match the original request",
        )

    # No existing idempotency key found, proceed with order creation
    # First, check the request body against any existing non-success records
    # (this shouldn't happen with our design)

    quantities: dict[uuid.UUID, int] = defaultdict(int)
    for item in body.items:
        quantities[item.product_id] += item.quantity
    product_ids = sorted(quantities, key=str)
    try:
        products = list(
            session.scalars(
                select(Product)
                .where(
                    Product.id.in_(product_ids),
                    Product.tenant_id == tenant,
                )
                .order_by(Product.id)
                .with_for_update()
            )
        )
        if len(products) != len(product_ids):
            raise ApiError(404, "NOT_FOUND", "Product not found")
        for product in products:
            if product.stock < quantities[product.id]:
                raise ApiError(
                    409,
                    "INSUFFICIENT_STOCK",
                    "Insufficient stock",
                )
        order = Order(
            tenant_id=tenant, status="PENDING", total_amount=0
        )
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

        # Record the success in idempotency_keys
        order_out = load_order(session, tenant, order.id)
        response_data = {
            "id": str(order_out.id),
            "tenant_id": str(order_out.tenant_id),
            "status": order_out.status,
            "total_amount": order_out.total_amount,
            "created_at": order_out.created_at.isoformat(),
            "updated_at": order_out.updated_at.isoformat(),
            "items": [
                {
                    "id": str(item.id),
                    "order_id": str(item.order_id),
                    "product_id": str(item.product_id),
                    "sku": item.sku,
                    "product_name": item.product_name,
                    "unit_price": item.unit_price,
                    "quantity": item.quantity,
                    "line_amount": item.line_amount,
                }
                for item in order_out.items
            ],
        }
        response_body_json = json.dumps(response_data)

        # Insert the idempotency key record
        idemp_key = IdempotencyKey(
            tenant_id=tenant,
            scope=scope,
            key=idempotency_key,
            response_body=response_body_json,
            status="SUCCESS",
        )
        session.add(idemp_key)
        session.commit()

        session.expire_all()
        return load_order(session, tenant, order.id)
    except ApiError:
        session.rollback()
        raise
