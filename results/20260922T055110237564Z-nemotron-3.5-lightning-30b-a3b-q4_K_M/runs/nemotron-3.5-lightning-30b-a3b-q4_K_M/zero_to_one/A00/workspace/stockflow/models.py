"""SQLAlchemy models for StockFlow Mini."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    UUID as SQLAlchemyUUID,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String=255, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("sku", "tenant_id", name="uq_product_sku_tenant"),
    )


class OrderStatus:
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"

    choices = [PENDING, CANCELLED]


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OrderStatus.PENDING
    )
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=False), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_amount: Mapped[int] = mapped_column(Integer, nullable=False)  # unit_price * quantity
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )