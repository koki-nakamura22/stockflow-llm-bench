import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        CheckConstraint("unit_price >= 0", name="ck_products_price"),
        CheckConstraint("stock >= 0", name="ck_products_stock"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    unit_price: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (CheckConstraint("total_amount >= 0", name="ck_orders_total"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    total_amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_order_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_price"),
        CheckConstraint("line_amount >= 0", name="ck_order_items_line"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    sku: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(200))
    unit_price: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    line_amount: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("key_length >= 1", name="ck_idempotency_key_length"),
        CheckConstraint("key_length <= 128", name="ck_idempotency_key_max_length"),
        UniqueConstraint("scope", "normalized_request_hash", name="uq_idempotency_scope_request"),
        UniqueConstraint("scope", "original_key", name="uq_idempotency_scope_original_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    original_key: Mapped[str] = mapped_column(String(128), nullable=False)
    key_length: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_data: Mapped[str] = mapped_column(String, nullable=False)
    response_data: Mapped[str | None] = mapped_column(String, nullable=True)