"""Order CRUD router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from stockflow.database import get_db
from stockflow.deps import get_tenant_id
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderItemCreate, OrderItemResponse, OrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Create a new order. Atomic operation: creates order and decrements stock."""
    # Validate all products exist and belong to the tenant
    product_map: dict[uuid.UUID, Product] = {}
    for item in payload.items:
        product = db.execute(
            select(Product).where(
                Product.id == item.product_id,
                Product.tenant_id == tenant_id,
            )
        ).scalars().first()

        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Product '{item.product_id}' not found",
                        "details": {"product_id": str(item.product_id)},
                    }
                },
            )
        product_map[item.product_id] = product

    # Aggregate items by product_id
    aggregated: dict[uuid.UUID, int] = {}
    for item in payload.items:
        aggregated[item.product_id] = aggregated.get(item.product_id, 0) + item.quantity

    # Check stock availability for all products
    for product_id, quantity in aggregated.items():
        product = product_map[product_id]
        if product.stock < quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "INSUFFICIENT_STOCK",
                        "message": f"Insufficient stock for product '{product_id}'",
                        "details": {
                            "product_id": str(product_id),
                            "requested": quantity,
                            "available": product.stock,
                        },
                    }
                },
            )

    # Create order and order items
    total_amount = 0
    order_items: list[OrderItem] = []

    for product_id, quantity in aggregated.items():
        product = product_map[product_id]
        line_amount = product.unit_price * quantity
        total_amount += line_amount

        order_item = OrderItem(
            product_id=product_id,
            sku=product.sku,
            product_name=product.name,
            unit_price=product.unit_price,
            quantity=quantity,
            line_amount=line_amount,
        )
        order_items.append(order_item)

    order = Order(
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=total_amount,
        items=order_items,
    )
    db.add(order)

    # Decrement stock atomically
    for product_id, quantity in aggregated.items():
        db.execute(
            update(Product)
            .where(Product.id == product_id, Product.tenant_id == tenant_id)
            .values(stock=Product.stock - quantity)
        )

    db.commit()
    db.refresh(order)

    # Reload with items
    order = db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items))
    ).scalars().first()

    return order


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Get an order by ID with items. Only returns orders belonging to the tenant."""
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    ).scalars().first()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Order '{order_id}' not found",
                    "details": {"order_id": str(order_id)},
                }
            },
        )

    return order


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Cancel an order. Only PENDING orders can be cancelled. Restores stock."""
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    ).scalars().first()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Order '{order_id}' not found",
                    "details": {"order_id": str(order_id)},
                }
            },
        )

    if order.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "INVALID_ORDER_STATE",
                    "message": f"Order '{order_id}' cannot be cancelled (status: {order.status})",
                    "details": {"order_id": str(order_id), "current_status": order.status},
                }
            },
        )

    # Update status to CANCELLED
    order.status = "CANCELLED"

    # Restore stock for all items
    for item in order.items:
        db.execute(
            update(Product)
            .where(Product.id == item.product_id, Product.tenant_id == tenant_id)
            .values(stock=Product.stock + item.quantity)
        )

    db.commit()
    db.refresh(order)

    # Reload with items
    order = db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items))
    ).scalars().first()

    return order
