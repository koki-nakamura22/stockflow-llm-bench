"""SQLAlchemy models for StockFlow."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stockflow.database import Base


class Product(Base):
                                                                                                                                        __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
               )
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    sku: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[int] = mapped_column(BigInteger)
    stock: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
               )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
               )

                     __table_args__ = (
        UniqueConstraint(
                                                                                                                                             "tenant_id", "sku", name="uq_products_tenant_sku"
                                                                                                                                         ),
                     )

    orders = relationship("Order", back_populates="product")


class Order(Base):
                                                                                                                                        __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
               )
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
               )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
               )

    items = relationship(
                                                                                                                                             "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
               )


class OrderItem(Base):
                                                                                                                                        __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
               )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE")
               )
    product_id: Mapped[uuid.UUID] = mapped_column(index=True)
    sku: Mapped[str] = mapped_column(String(100))
    product_name: Mapped[str] = mapped_column(String(255))
    unit_price: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(BigInteger)
    line_amount: Mapped[int] = mapped_column(BigInteger)

    order = relationship("Order", back_populates="items")
