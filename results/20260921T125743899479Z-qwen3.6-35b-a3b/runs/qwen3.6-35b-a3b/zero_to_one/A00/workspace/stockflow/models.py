"""SQLAlchemy models for StockFlow Mini."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku: Mapped[str] = Column(String(255), nullable=False, index=True)
    name: Mapped[str] = Column(Text, nullable=False)
    unit_price: Mapped[int] = Column(Integer, nullable=False)
    stock: Mapped[int] = Column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = Column(default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = Column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    items: Mapped[list[OrderItem]] = relationship("OrderItem", back_populates="product")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = Column(String(50), nullable=False, default="PENDING")
    total_amount: Mapped[int] = Column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = Column(default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = Column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    items: Mapped[list[OrderItem]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = Column(UUID(as_uuid=True), nullable=False)
    sku: Mapped[str] = Column(String(255), nullable=False)
    product_name: Mapped[str] = Column(Text, nullable=False)
    unit_price: Mapped[int] = Column(Integer, nullable=False)
    quantity: Mapped[int] = Column(Integer, nullable=False)
    line_amount: Mapped[int] = Column(Integer, nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")
    product: Mapped[Product] = relationship("Product", back_populates="items")
