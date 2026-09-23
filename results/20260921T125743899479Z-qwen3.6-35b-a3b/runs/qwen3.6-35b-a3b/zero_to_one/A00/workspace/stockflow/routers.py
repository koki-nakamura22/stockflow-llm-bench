"""API routers for StockFlow Mini."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stockflow.database import get_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import (
    ErrorResponse,
    ErrorDetail,
    OrderCreate,
    OrderItemResponse,
    OrderResponse,
    ProductCreate,
    ProductResponse,
)

router = APIRouter()


# --- Exception classes for error handling ---


class InvalidTenantError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=400,
            detail=ErrorResponse(
                error=ErrorDetail(code="INVALID_TENANT", message="Invalid tenant ID", details={})
            ).model_dump(),
        )


class NotFoundError(HTTPException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorDetail(code="NOT_FOUND", message=f"{resource} not found", details={})
            ).model_dump(),
        )


class DuplicateSKUError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=409,
            detail=ErrorResponse(
                error=ErrorDetail(code="SKU_ALREADY_EXISTS", message="SKU already exists", details={})
            ).model_dump(),
        )


class InsufficientStockError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=409,
            detail=ErrorResponse(
                error=ErrorDetail(code="INSUFFICIENT_STOCK", message="Insufficient stock", details={})
            ).model_dump(),
        )


class InvalidOrderStateError(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=409,
            detail=ErrorResponse(
                error=ErrorDetail(code="INVALID_ORDER_STATE", message="Invalid order state", details={})
            ).model_dump(),
        )


def _invalid_tenant() -> InvalidTenantError:
    return InvalidTenantError()


def _product_not_found() -> NotFoundError:
    return NotFoundError("Product")


def _order_not_found() -> NotFoundError:
    return NotFoundError("Order")


def _validate_tenant(x_tenant_id: str) -> uuid.UUID:
    """Validate tenant header and return UUID."""
    try:
        return uuid.UUID(x_tenant_id)
    except (ValueError, TypeError):
        raise _invalid_tenant()


# --- Health ---


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# --- Products ---


@router.post("/products", status_code=201)
async def create_product(
    body: ProductCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    tenant_id = _validate_tenant(x_tenant_id)

    # Check if SKU already exists for this tenant
    existing = await session.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.sku == body.sku,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateSKUError()

    product = Product(
        tenant_id=tenant_id,
        sku=body.sku,
        name=body.name,
        unit_price=body.unit_price,
        stock=body.stock,
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.get("/products/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    tenant_id = _validate_tenant(x_tenant_id)

    product = await session.get(Product, product_id)
    if product is None or product.tenant_id != tenant_id:
        raise _product_not_found()
    return product


# --- Orders ---


@router.post("/orders", status_code=201)
async def create_order(
    body: OrderCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    tenant_id = _validate_tenant(x_tenant_id)

    # Aggregate items by product_id
    aggregated: dict[uuid.UUID, int] = defaultdict(int)
    for item in body.items:
        aggregated[item.product_id] += item.quantity

    product_ids = list(aggregated.keys())

    # Fetch all products with row-level locking in a single query
    result = await session.execute(
        select(Product).where(Product.id.in_(product_ids)).with_for_update()
    )
    products = {p.id: p for p in result.scalars().all()}

    # Validate all products exist and belong to tenant
    for pid in product_ids:
        if pid not in products:
            raise _product_not_found()
        if products[pid].tenant_id != tenant_id:
            raise _product_not_found()

    # Check stock availability
    for pid, qty in aggregated.items():
        product = products[pid]
        if product.stock < qty:
            raise InsufficientStockError()

    # Create order
    order = Order(
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=0,
    )
    session.add(order)
    await session.flush()  # Get order.id

    # Create order items and deduct stock
    total_amount = 0
    for item in body.items:
        product = products[item.product_id]
        line_amount = product.unit_price * item.quantity
        total_amount += line_amount

        order_item = OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            sku=product.sku,
            product_name=product.name,
            unit_price=product.unit_price,
            quantity=item.quantity,
            line_amount=line_amount,
        )
        session.add(order_item)
        product.stock -= item.quantity

    order.total_amount = total_amount
    await session.commit()
    await session.refresh(order)
    return order


@router.get("/orders/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    tenant_id = _validate_tenant(x_tenant_id)

    order = await session.get(Order, order_id)
    if order is None or order.tenant_id != tenant_id:
        raise _order_not_found()
    return order


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    tenant_id = _validate_tenant(x_tenant_id)

    order = await session.get(Order, order_id)
    if order is None or order.tenant_id != tenant_id:
        raise _order_not_found()

    if order.status != "PENDING":
        raise InvalidOrderStateError()

    # Lock the order and its items
    order_result = await session.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    order = order_result.scalar_one()

    items_result = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).with_for_update()
    )
    items = items_result.scalars().all()

    # Restore stock
    for item in items:
        product_result = await session.execute(
            select(Product).where(Product.id == item.product_id).with_for_update()
        )
        product = product_result.scalar_one()
        product.stock += item.quantity

    order.status = "CANCELLED"
    await session.commit()
    await session.refresh(order)
    return order
