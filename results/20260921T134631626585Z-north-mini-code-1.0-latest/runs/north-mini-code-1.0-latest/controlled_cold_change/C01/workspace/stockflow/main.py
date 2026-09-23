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
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut, OrderQuery, OrderPage
from stockflow.utils import encode_cursor, decode_cursor

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
# New endpoint for paginated orders
@app.get("/orders", response_model=OrderPage)
def list_orders(
    query: OrderQuery = Depends(),
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> OrderPage:
    """List orders with cursor pagination."""
    # Validate cursor if provided
    cursor_data = None
    if query.cursor:
        try:
            cursor_data = decode_cursor(query.cursor)
        except ValueError:
            raise ApiError(400, "INVALID_CURSOR", "Invalid or tampered cursor")
        # Validate that cursor's filters match current query
        if cursor_data["status"] != query.status:
            raise ApiError(400, "INVALID_CURSOR", "Filter status mismatch")
        if cursor_data["created_from"] != query.created_from:
            raise ApiError(400, "INVALID_CURSOR", "Filter created_from mismatch")
        if cursor_data["created_to"] != query.created_to:
            raise ApiError(400, "INVALID_CURSOR", "Filter created_to mismatch")

    # Build WHERE clause
    where_clauses = [Order.tenant_id == tenant]
    if query.status is not None:
        where_clauses.append(Order.status == query.status)
    if query.created_from is not None:
        where_clauses.append(Order.created_at >= query.created_from)
    if query.created_to is not None:
        where_clauses.append(Order.created_at <= query.created_to)
    # If we have a cursor, add exclusive filter based on keyset pagination
    if cursor_data is not None:
        last_created_at = cursor_data["created_at"]
        last_order_id = cursor_data["id"]
        where_clauses.append(
            (Order.created_at < last_created_at) |
            ((Order.created_at == last_created_at) & (Order.id < last_order_id))
        )

    # Order by the same ordering used for pagination
    stmt = select(Order).where(*where_clauses).order_by(Order.created_at.desc(), Order.id.desc())

    # Apply limit (but we need to fetch limit + 1 to detect next page)
    limit = query.limit + 1
    stmt = stmt.limit(limit)

    orders = session.scalars(stmt).all()

    # Determine next cursor
    next_cursor = None
    if len(orders) > query.limit:
        # There is a next page, take the last order for cursor (the one after the limit)
        # The last order of this page is orders[-1] (since we fetched limit+1)
        last_of_page = orders[-1]
        next_cursor = encode_cursor(
            created_at=last_of_page.created_at,
            order_id=last_of_page.id,
            status=query.status,
            created_from=query.created_from,
            created_to=query.created_to,
        )
        # Slice to only the first limit orders
        orders = orders[:query.limit]

    # Eager load items for each order
    for order in orders:
        session.expire(order, ['items'])
        session.refresh(order, ['items'])

    # Convert to OrderOut via the schema (simple model_dump)
    order_outs = []
    for order in orders:
        order_outs.append(OrderOut.model_validate(order))

    return OrderPage(items=order_outs, next_cursor=next_cursor)