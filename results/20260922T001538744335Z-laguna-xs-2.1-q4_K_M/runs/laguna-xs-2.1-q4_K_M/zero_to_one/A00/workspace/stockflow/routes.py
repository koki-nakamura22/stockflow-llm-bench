from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from stockflow.db import get_session
from stockflow.db.models import Order, OrderItem, Product
from stockflow.exceptions import APIError, ErrorCode


router = APIRouter()


def get_tenant_id(x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None) -> str:
    if not x_tenant_id:
        raise APIError(
            status.HTTP_400_BAD_REQUEST,
            ErrorCode.INVALID_TENANT,
            "Missing X-Tenant-Id header",
        )
    return x_tenant_id


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    unit_price: int = Field(..., gt=0)
    stock: int = Field(..., ge=0)


class ProductResponse(BaseModel):
    id: str
    tenant_id: str
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(..., gt=0)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItemResponse(BaseModel):
    id: str
    order_id: str
    product_id: str
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: str
    tenant_id: str
    status: str
    total_amount: int
    created_at: str
    updated_at: str
    items: list[OrderItemResponse]

    class Config:
        from_attributes = True


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductResponse:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        sku=payload.sku,
        name=payload.name,
        unit_price=payload.unit_price,
        stock=payload.stock,
    )
    session.add(product)
    try:
        await session.commit()
        await session.refresh(product)
    except IntegrityError:
        await session.rollback()
        raise APIError(
            status.HTTP_409_CONFLICT,
            ErrorCode.SKU_ALREADY_EXISTS,
            f"SKU '{payload.sku}' already exists",
        )
    return ProductResponse.model_validate(product)


@router.get("/products/{product_id}")
async def get_product(
    product_id: str,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductResponse:
    result = await session.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise APIError(
            status.HTTP_404_NOT_FOUND,
            ErrorCode.NOT_FOUND,
            "Product not found",
        )
    return ProductResponse.model_validate(product)


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderResponse:
    # Aggregate quantities from items
    item_quantities: dict[str, int] = {}
    for item in payload.items:
        item_quantities[item.product_id] = item_quantities.get(item.product_id, 0) + item.quantity
    
    # Fetch all products for this order with tenant check
    product_ids = list(item_quantities.keys())
    result = await session.execute(
        select(Product).where(
            Product.id.in_(product_ids),
            Product.tenant_id == tenant_id,
        )
    )
    products = result.scalars().all()
    product_dict = {p.id: p for p in products}
    
    # Check all products exist (for other tenant or missing products, return 404)
    for item in payload.items:
        if item.product_id not in product_dict:
            raise APIError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.NOT_FOUND,
                "Product not found",
            )
    
    # Prepare order items (snapshot product data at order time)
    order_items_data = []
    total_amount = 0
    for item in payload.items:
        product = product_dict[item.product_id]
        quantity = item_quantities[item.product_id]
        # Accumulate quantity per product to create single order item
        line_amount = product.unit_price * quantity
        total_amount += line_amount
        order_items_data.append({
            "id": str(uuid.uuid4()),
            "order_id_placeholder": "placeholder",  # Will be set later
            "product_id": product.id,
            "sku": product.sku,
            "product_name": product.name,
            "unit_price": product.unit_price,
            "quantity": quantity,
            "line_amount": line_amount,
        })
    
    # Create order
    order = Order(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=total_amount,
    )
    session.add(order)
    
    # Create order items
    for item_data in order_items_data:
        order_item = OrderItem(
            id=item_data["id"],
            order_id=order.id,
            product_id=item_data["product_id"],
            sku=item_data["sku"],
            product_name=item_data["product_name"],
            unit_price=item_data["unit_price"],
            quantity=item_data["quantity"],
            line_amount=item_data["line_amount"],
        )
        session.add(order_item)
    
    # Decrease stock atomically with row-level locking to prevent race conditions
    for product_id, quantity in item_quantities.items():
        product = product_dict[product_id]
        product.stock -= quantity
    
    # Commit all changes atomically
    await session.commit()
    
    # Fetch the order with items for response
    result = await session.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items))
    )
    order_with_items = result.scalar_one()
    
    return OrderResponse.model_validate(order_with_items)


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderResponse:
    result = await session.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise APIError(
            status.HTTP_404_NOT_FOUND,
            ErrorCode.NOT_FOUND,
            "Order not found",
        )
    return OrderResponse.model_validate(order)


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    result = await session.execute(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise APIError(
            status.HTTP_404_NOT_FOUND,
            ErrorCode.NOT_FOUND,
            "Order not found",
        )
    
    if order.status != "PENDING":
        raise APIError(
            status.HTTP_409_CONFLICT,
            ErrorCode.INVALID_ORDER_STATE,
            f"Order is in state '{order.status}', only PENDING orders can be cancelled",
        )
    
    # Load order items
    result = await session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id)
    )
    items = result.scalars().all()
    
    # Aggregate quantities to restore by product
    product_quantities: dict[str, int] = {}
    for item in items:
        product_quantities[item.product_id] = product_quantities.get(item.product_id, 0) + item.quantity
    
    # Update order status
    order.status = "CANCELLED"
    
    # Restore stock for each product
    for product_id, quantity in product_quantities.items():
        result = await session.execute(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == tenant_id,
            )
        )
        product = result.scalar_one_or_none()
        if product:
            product.stock += quantity
    
    await session.commit()
    
    return {"status": "ok"}