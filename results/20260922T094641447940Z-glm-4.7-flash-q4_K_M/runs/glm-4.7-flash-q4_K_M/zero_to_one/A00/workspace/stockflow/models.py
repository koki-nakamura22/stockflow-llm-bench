"""SQLAlchemy models for StockFlow."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for all models."""


class Tenant(Base):
    """Tenant model (for isolation)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Product(Base):
    """Product model."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Order(Base):
    """Order model."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class OrderItem(Base):
    """Order item model."""

    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    order_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_amount: Mapped[int] = mapped_column(Integer, nullable=False)