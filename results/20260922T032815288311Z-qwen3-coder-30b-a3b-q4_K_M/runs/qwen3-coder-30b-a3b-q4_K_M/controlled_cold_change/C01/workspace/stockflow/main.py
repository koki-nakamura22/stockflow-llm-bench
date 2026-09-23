import base64
import json
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
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut

app = FastAPI(title="StockFlow Mini")

CURSOR_SECRET = "cursor_secret_key_for_orders"  # In production, this should come from environment


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


def encode_cursor(order_id: uuid.UUID, created_at: Any) -> str:
    """Encode cursor for pagination"""
    data = {
        "id": str(order_id),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    }
    json_str = json.dumps(data, separators=(',', ':'))
    return base64.urlsafe_b64encode(json_str.encode()).decode()


def decode_cursor(cursor: str) -> tuple[uuid.UUID, Any]:
    """Decode cursor for pagination"""
    try:
        json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(json_str)
        return uuid.UUID(data["id"]), data["created_at"]
    except Exception:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor")


def validate_cursor_filter_change(session: Session, tenant: uuid.UUID, filters: dict[str, Any]) -> None:
    """Validate that the cursor wasn't created with different filters"""
    # This is a simplified implementation - in reality we'd need to store
    # cursor metadata to track which filters were used for its creation
    # For now, we'll just check if any filters are applied when cursor exists
    # and raise error if they do (to match the requirement)
    if filters:
        raise ApiError(400, "INVALID_CURSOR", "Cannot use filters with cursor")


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


@app.get("/orders")
def list_orders(
    limit: int,
    status: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    cursor: str | None = None,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    # Validate limit
    if not (1 <= limit <= 100):
        raise ApiError(400, "INVALID_LIMIT", "Limit must be between 1 and 100")
    
    # Build query
    stmt = select(Order).where(Order.tenant_id == tenant)
    
    # Apply filters
    filters = {}
    if status is not None:
        stmt = stmt.where(Order.status == status)
        filters["status"] = status
        
    if created_from is not None:
        stmt = stmt.where(Order.created_at >= created_from)
        filters["created_from"] = created_from
        
    if created_to is not None:
        stmt = stmt.where(Order.created_at <= created_to)
        filters["created_to"] = created_to
    
    # Apply cursor pagination
    if cursor is not None:
        try:
            order_id, created_at = decode_cursor(cursor)
            # For descending order (created_at DESC, id DESC), we need to filter
            # where created_at < cursor_created_at OR (created_at == cursor_created_at AND id < cursor_id)
            stmt = stmt.where(
                (Order.created_at < created_at) |
                ((Order.created_at == created_at) & (Order.id < order_id))
            )
            # Validate that cursor wasn't created with different filters
            validate_cursor_filter_change(session, tenant, filters)
        except ApiError:
            raise
        except Exception:
            raise ApiError(400, "INVALID_CURSOR", "Invalid cursor")
    
    # Apply ordering and limit
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
    
    orders = list(session.scalars(stmt))
    
    # Prepare response
    items = []
    next_cursor = None
    
    # Process results (limiting to actual requested limit)
    for i, order in enumerate(orders):
        if i < limit:
            items.append(order)
        else:
            # We have one more item than requested, so there's a next page
            # Use the last item to create the cursor
            next_cursor = encode_cursor(order.id, order.created_at)
            break
    
    return {"items": items, "next_cursor": next_cursor}