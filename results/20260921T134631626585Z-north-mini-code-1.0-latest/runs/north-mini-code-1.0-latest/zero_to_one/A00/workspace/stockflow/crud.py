"""CRUD operations for StockFlow."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, update, delete, exc
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from stockflow.models import Base, Product, Order, OrderItem

# Helper to generate UUID

def generate_uuid() -> uuid.UUID:
    return uuid.uuid4()

# Product CRUD

def create_product(session: Session, tenant_id: uuid.UUID, sku: str, name: str, unit_price: int, stock: int) -> Product:
    product = Product(
        id=generate_uuid(),
        tenant_id=tenant_id,
        sku=sku,
        name=name,
        unit_price=unit_price,
: int = stock,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(product)
    session.flush()
    return product


def get_product_by_id(session: Session, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Product]:
    return session.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    )


def get_product_by_sku(session: Session, tenant_id: uuid.UUID, sku: str) -> Optional[Product]:
    return session.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku)
    )


def update_product_stock(session: Session, product_id: uuid.UUID, new_stock: int) -> None:
    session.execute(
        update(Product)
        .where(Product.id == product_id)
        .values(stock=new_stock, updated_at=datetime.now(timezone.utc))
    )

# Order CRUD

def create_order(session: Session, tenant_id: uuid.UUID, total_amount: int) -> Order:
    order = Order(
        id=generate_uuid(),
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=total_amount,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(order)
    session.flush()
    return order


def get_order_by_id(session: Session, order_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Order]:
    return session.scalar(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )


def update_order_status(session: Session, order_id: uuid.UUID, status: str) -> None:
    session.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(status=status, updated_at=datetime.now(timezone.utc))
    )


def add_order_items(session: Session, order_id: uuid.UUID, items_data: List[dict]) -> None:
    # items_data: list of dicts with keys product_id, sku, product_name, unit_price, quantity, line_amount
    for data in items_data:
        order_item = OrderItem(
            id=generate_uuid(),
            order_id=order_id,
            product_id=data["product_id"],
            sku=data["sku"],
            product_name=data["product_name"],
            unit_price=data["unit_price"],
            quantity=data["quantity"],
            line_amount=data["line_amount"],
        )
        session.add(order_item)


def get_order_items_by_order(session: Session, order_id: uuid.UUID) -> List[OrderItem]:
    return session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id)
    ).all()

# Stock adjustment utilities

def decrement_product_stock(session: Session, product_id: uuid.UUID, quantity: int) -> None:
    session.execute(
        update(Product)
        .where(Product.id == product_id)
        .values(stock=session.query(Product.stock).filter(Product.id == product_id).scalar_subquery() - quantity,
                updated_at=datetime.now(timezone.utc))
    )


def increment_product_stock(session: Session, product_id: uuid.UUID, quantity: int) -> None:
    session.execute(
        update(Product)
        .where(Product.id == product_id)
        .values(stock=session.query(Product.stock).filter(Product.id == product_id).scalar_subquery() + quantity,
                updated_at=datetime.now(timezone.utc))
    )