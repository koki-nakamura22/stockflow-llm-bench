"""StockFlow Mini database models."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = Column(Uuid, primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    tenant_id: Mapped[str] = Column(Uuid, nullable=False)
    sku: Mapped[str] = Column(String(255), nullable=False)
    name: Mapped[str] = Column(String(255), nullable=False)
    unit_price: Mapped[int] = Column(Integer, nullable=False)
    stock: Mapped[int] = Column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = Column(Uuid, primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    tenant_id: Mapped[str] = Column(Uuid, nullable=False)
    status: Mapped[str] = Column(String(50), nullable=False, default="PENDING")
    total_amount: Mapped[int] = Column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = Column(Uuid, primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    order_id: Mapped[str] = Column(Uuid, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[str] = Column(Uuid, nullable=False)
    sku: Mapped[str] = Column(String(255), nullable=False)
    product_name: Mapped[str] = Column(String(255), nullable=False)
    unit_price: Mapped[int] = Column(Integer, nullable=False)
    quantity: Mapped[int] = Column(Integer, nullable=False)
    line_amount: Mapped[int] = Column(Integer, nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
