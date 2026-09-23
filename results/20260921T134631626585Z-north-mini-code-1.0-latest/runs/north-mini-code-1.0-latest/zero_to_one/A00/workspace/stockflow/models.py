"""SQLAlchemy models for StockFlow."""

from datetime import datetime, timezone
from typing import List

from sqlalchemy import Column, DateTime, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    unit_price = Column(Integer, nullable=False)
    stock = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uix_tenant_sku"),
    )

    # Relationship to orders (through order_items)
    order_items = relationship("OrderItem", back_populates="product")


class Order(Base):
    __tablename__ = "orders"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False)
    status = Column(String, nullable=False)  # e.g., "PENDING", "CANCELLED"
    total_amount = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship to order_items
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    order_id = Column(PG_UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    product_id = Column(PG_UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    sku = Column(String, nullable=False)  # snapshot
    product_name = Column(String, nullable=False)  # snapshot
    unit_price = Column(Integer, nullable=False)  # snapshot
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Integer, nullable=False)  # unit_price * quantity

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")