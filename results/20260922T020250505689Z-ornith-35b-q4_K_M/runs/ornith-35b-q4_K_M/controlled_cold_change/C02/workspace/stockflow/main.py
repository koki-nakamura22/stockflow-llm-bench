import json
import uuid
from collections import defaultdict
from hashlib import sha256
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session
from stockflow.models import IdempotencyKey, Order, OrderItem, Product
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


def idempotency_key_header(x_idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    if x_idempotency_key is None:
        raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required")
    if len(x_idempotency_key) < 1 or len(x_idempotency_key) > 128:
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1-128 ASCII characters")
    if not x_idempotency_key.isascii():
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be ASCII characters")
    return x_idempotency_key


def normalize_request_body(body: OrderCreate) -> str:
    data = body.model_dump()
    # Sort items by product_id for canonical order
    data["items"] = sorted(data["items"], key=lambda x: str(x["product_id"]))
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_request_hash(normalized: str) -> str:
    return sha256(normalized.encode("utf-8")).hexdigest()


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
    ikey: str = Depends(idempotency_key_header),
    session: Session = Depends(get_session),
) -> Order:
    endpoint = "/orders"
    normalized = normalize_request_body(body)
    request_hash = compute_request_hash(normalized)

    # Try to find existing idempotency record with row lock for concurrency control
    lookup_stmt = (
        select(IdempotencyKey)
        .where(
            IdempotencyKey.tenant_id == tenant,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.idempotency_key == ikey,
        )
        .with_for_update()
    )
    record = session.scalar(lookup_stmt)

    if record is not None:
        if record.status == "SUCCESS":
            # Cache hit: return the original successful response
            # Re-fetch the order using the stored order_id
            if record.order_id is not None:
                order = load_order(session, tenant, record.order_id)
                session.commit()
                return order
            # Should not happen: SUCCESS without order_id
            session.rollback()
            raise ApiError(500, "INTERNAL_ERROR", "Idempotency record corrupted")
        if record.request_hash != request_hash:
            # Conflict: same key used with a different request body
            session.rollback()
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key already used with different request")
        # Same hash, non-SUCCESS status: proceed with the order (overwrite PENDING/FAILURE)

    # No existing record: create one with PENDING status
    record = IdempotencyKey(
        tenant_id=tenant,
        endpoint=endpoint,
        idempotency_key=ikey,
        request_hash=request_hash,
        status="PENDING",
    )
    session.add(record)
    session.flush()

    # Execute the order creation logic
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

        # Mark idempotency record as SUCCESS and store result
        record.status = "SUCCESS"
        record.order_id = order.id
        record.result_status = 201
        order_out = _order_to_out(session, tenant, order)
        record.result_body = order_out.model_dump_json()
        session.commit()

    except ApiError:
        session.rollback()
        # Failure: do NOT record as success; mark as FAILURE
        record.status = "FAILURE"
        record.order_id = None
        record.result_status = None
        record.result_body = None
        session.commit()
        raise
    except Exception:
        session.rollback()
        record.status = "FAILURE"
        record.order_id = None
        record.result_status = None
        record.result_body = None
        session.commit()
        raise

    session.expire_all()
    return load_order(session, tenant, order.id)


def _order_to_out(session: Session, tenant: uuid.UUID, order: Order) -> OrderOut:
    """Serialize an Order ORM instance to OrderOut."""
    items = [
        OrderItemOut(
            id=item.id,
            order_id=item.order_id,
            product_id=item.product_id,
            sku=item.sku,
            product_name=item.product_name,
            unit_price=item.unit_price,
            quantity=item.quantity,
            line_amount=item.line_amount,
        )
        for item in order.items
    ]
    return OrderOut(
        id=order.id,
        tenant_id=order.tenant_id,
        status=order.status,
        total_amount=order.total_amount,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=items,
    )


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
