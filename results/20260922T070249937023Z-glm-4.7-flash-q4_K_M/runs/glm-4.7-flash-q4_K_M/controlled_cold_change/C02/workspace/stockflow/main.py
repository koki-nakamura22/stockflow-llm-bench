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


class IdempotencyService:
    @staticmethod
    def normalize_request(body: OrderCreate) -> str:
        """Normalize request for idempotency check"""
        # Sort items by product_id to ensure consistent hashing
        sorted_items = sorted(body.items, key=lambda item: str(item.product_id))
        normalized = {
            "items": [
                {"product_id": str(item.product_id), "quantity": item.quantity}
                for item in sorted_items
            ]
        }
        return hashlib.sha256(
            str(normalized).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def get_idempotency_key(
        x_tenant_id: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None),
    ) -> tuple[uuid.UUID, str]:
        """Extract and validate idempotency key"""
        try:
            if x_tenant_id is None:
                raise ValueError
            tenant_id = uuid.UUID(x_tenant_id)
        except ValueError as exc:
            raise ApiError(400, "INVALID_TENANT", "X-Tenant-Id must be a UUID") from exc

        if idempotency_key is None:
            raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key header is required")

        return tenant_id, idempotency_key

    def check_key_exists(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        key: str,
        request_hash: str,
    ) -> uuid.UUID | None:
        """Check if idempotency key exists and matches request hash"""
        stmt = (
            select(IdempotencyKey)
            .where(
                IdempotencyKey.tenant_id == tenant_id,
                IdempotencyKey.key == key,
                IdempotencyKey.request_hash == request_hash,
            )
        )
        result = session.scalar(stmt)
        if result and result.order_id:
            return result.order_id
        return None

    def store_key(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        key: str,
        request_hash: str,
        order_id: uuid.UUID,
    ) -> None:
        """Store idempotency key"""
        idempotency_key = IdempotencyKey(
            tenant_id=tenant_id,
            key=key,
            request_hash=request_hash,
            order_id=order_id,
        )
        session.add(idempotency_key)
        session.commit()


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
    # Check idempotency key
    tenant_id, key = IdempotencyService.get_idempotency_key(
        x_tenant_id=tenant,
        idempotency_key=body.idempotency_key,
    )
    request_hash = IdempotencyService.normalize_request(body)

    # Check existing key
    existing_order_id = IdempotencyService.check_key_exists(
        session, tenant_id, key, request_hash
    )
    if existing_order_id:
        existing_order = load_order(session, tenant_id, existing_order_id)
        if existing_order.status in ["PENDING", "CONFIRMED", "COMPLETED"]:
            session.expire_all()
            return existing_order
        else:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Request hash differs from previous request")

    # Create new order
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
        order = Order(tenant_id=tenant, status="PENDING", total_amount=0, idempotency_key=key)
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
        # Store idempotency key
        IdempotencyService.store_key(session, tenant_id, key, request_hash, order.id)
    except IntegrityError:
        # Handle potential race condition
        session.rollback()
        raise ApiError(409, "ORDER_ALREADY_EXISTS", "Order already exists") from None
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
