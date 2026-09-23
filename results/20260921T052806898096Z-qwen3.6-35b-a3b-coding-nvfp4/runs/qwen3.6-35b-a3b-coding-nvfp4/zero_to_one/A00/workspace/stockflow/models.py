"""SQLAlchemy models for StockFlow Mini."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id = Column(Uuid, primary_key=True)
    tenant_id = Column(Uuid, nullable=False, index=True)
    sku = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    unit_price = Column(Integer, nullable=False)
    stock = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Unique constraint on tenant_id + sku
        # Note: SQLAlchemy 2.x uses __table_args__ for constraints
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(Uuid, primary_key=True)
    tenant_id = Column(Uuid, nullable=False, index=True)
    status = Column(String(50), nullable=False, default="PENDING")
    total_amount = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Uuid, primary_key=True)
    order_id = Column(Uuid, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Uuid, nullable=False)
    sku = Column(String(255), nullable=False)
    product_name = Column(String(255), nullable=False)
    unit_price = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
