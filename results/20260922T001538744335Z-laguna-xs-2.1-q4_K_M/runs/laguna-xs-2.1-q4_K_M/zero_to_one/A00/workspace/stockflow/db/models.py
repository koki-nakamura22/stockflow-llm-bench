from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, String, DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from sqlalchemy import Column, ForeignKey


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_tenant_id_sku", "tenant_id", "sku", unique=True),
        Index("ix_products_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sku: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_amount: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")