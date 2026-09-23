import hashlib
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


def idempotency_key_header(x_idempotency_key: str | None = Header(default=None)) -> str:
    if x_idempotency_key is None:
        raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required")
    if len(x_idempotency_key) < 1 or len(x_idempotency_key) > 128:
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1-128 ASCII characters")
    if not all(32 <= ord(c) <= 126 for c in x_idempotency_key):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must contain only ASCII characters")
    return x_idempotency_key


def compute_request_hash(body: OrderCreate) -> str:
    """Compute a hash of the normalized request body for idempotency comparison."""
    items = sorted(body.items, key=lambda x: str(x.product_id))
    normalized = f"{len(items)}"
    for item in items:
        normalized += f"|{item.product_id}:{item.quantity}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
    idempotency_key: str = Depends(idempotency_key_header),
    session: Session = Depends(get_session),
) -> Order:
    endpoint = "/orders"
    request_hash = compute_request_hash(body)

    # Check for existing idempotency key
    existing = session.scalar(
        select(IdempotencyKey)
        .where(
            IdempotencyKey.tenant_id == tenant,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.idempotency_key == idempotency_key,
        )
    )

    if existing is not None:
        if existing.request_hash != request_hash:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key used with different request")
        # Same request - return stored response
        return OrderOut.model_validate_json(existing.response_body)

    # No existing key - proceed with order creation
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
    except Exception:
        session.rollback()
        raise

    # Store idempotency key with success response
    stored_order = load_order(session, tenant, order.id)
    order_out = OrderOut.model_validate(stored_order)
    response_body = order_out.model_dump_json()

    # Use select for update to handle concurrent requests
    try:
        idemp_key = IdempotencyKey(
            tenant_id=tenant,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=201,
            response_body=response_body,
        )
        session.add(idemp_key)
        session.commit()
    except IntegrityError:
        # Concurrent request won the race - fetch the existing one
        session.rollback()
        existing = session.scalar(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == tenant,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
        )
        return OrderOut.model_validate_json(existing.response_body)

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
