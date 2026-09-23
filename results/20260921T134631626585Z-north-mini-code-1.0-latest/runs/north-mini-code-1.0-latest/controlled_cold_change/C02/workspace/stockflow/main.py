import uuid
from collections import defaultdict
from typing import Any
import hashlib
import json

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import Order, OrderItem, Product, IdempotencyRecord
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


def get_idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    if idempotency_key is None:
        raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required")
    if not (1 <= len(idempotency_key) <= 128):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1-128 characters")
    if not idempotency_key.isprintable():
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must contain only printable ASCII characters")
    return idempotency_key


def normalize_request(request_data: dict[str, Any]) -> str:
    """Normalize request data for idempotency checking"""
    # Sort keys to ensure consistent ordering
    return json.dumps(request_data, sort_keys=True, separators=(',', ':'))


def get_normalized_request_hash(request_data: dict[str, Any]) -> str:
    """Get a hash of the normalized request"""
    normalized = normalize_request(request_data)
    return hashlib.sha256(normalized.encode()).hexdigest()


def create_idempotency_scope(tenant_id: uuid.UUID, endpoint: str, key: str) -> str:
    """Create the idempotency scope"""
    return f"{tenant_id}:{endpoint}:{key}"


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


@app.post("/orders", response_model=OrderOut, status_code=201)
def create_order(
    body: OrderCreate,
    tenant: uuid.UUID = Depends(tenant_id),
    idempotency_key: str = Depends(get_idempotency_key),
    session: Session = Depends(get_session),
) -> Order:
    endpoint = "/orders"
    scope = create_idempotency_scope(tenant, endpoint, idempotency_key)
    request_data = body.model_dump()
    request_hash = get_normalized_request_hash(request_data)

    # Check if we already have an idempotency record for this scope
    existing_record = session.scalar(
        select(IdempotencyRecord)
        .where(IdempotencyRecord.scope == scope, IdempotencyRecord.original_key == idempotency_key)
    )

    if existing_record:
        # If we have a record but no order_id, this is a failed attempt
        if existing_record.order_id is None:
            # Remove the failed record and try again
            session.delete(existing_record)
            session.flush()
        # If we have a record with order_id, check if the request matches
        elif existing_record.order_id is not None:
            # If the request differs, return conflict
            if existing_record.normalized_request_hash != request_hash:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency conflict: request differs from original")
            # If the request matches, return the existing order
            return load_order(session, tenant, existing_record.order_id)

    # Create order with inventory check
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
            # This is a failed attempt, record it for idempotency
            record = IdempotencyRecord(
                scope=scope,
                original_key=idempotency_key,
                key_length=len(idempotency_key),
                normalized_request_hash=request_hash,
                request_data=json.dumps(request_data, sort_keys=True, separators=(',', ':')),
            )
            session.add(record)
            session.commit()
            raise ApiError(404, "NOT_FOUND", "Product not found")
        for product in products:
            if product.stock < quantities[product.id]:
                # This is a failed attempt, record it for idempotency
                record = IdempotencyRecord(
                    scope=scope,
                    original_key=idempotency_key,
                    key_length=len(idempotency_key),
                    normalized_request_hash=request_hash,
                    request_data=json.dumps(request_data, sort_keys=True, separators=(',', ':')),
                )
                session.add(record)
                session.commit()
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

        # Create or update idempotency record
        existing_record = session.scalar(
            select(IdempotencyRecord)
            .where(IdempotencyRecord.scope == scope, IdempotencyRecord.original_key == idempotency_key)
        )
        if existing_record:
            existing_record.order_id = order.id
            existing_record.response_data = json.dumps(order.model_dump())
        else:
            record = IdempotencyRecord(
                scope=scope,
                original_key=idempotency_key,
                key_length=len(idempotency_key),
                normalized_request_hash=request_hash,
                order_id=order.id,
                request_data=json.dumps(request_data, sort_keys=True, separators=(',', ':')),
                response_data=json.dumps(order.model_dump()),
            )
            session.add(record)

        session.commit()
    except ApiError:
        session.rollback()
        raise
    except Exception:
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