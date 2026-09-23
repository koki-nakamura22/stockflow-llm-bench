import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
        CheckConstraint("unit_price \u003e= 0", name="ck_products_price"),
        CheckConstraint("stock \u003e= 0", name="ck_products_stock"),
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
    __table_args__ = (CheckConstraint("total_amount \u003e= 0", name="ck_orders_total"),)

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
        CheckConstraint("quantity \u003e= 0", name="ck_order_items_quantity"),
        CheckConstraint("unit_price \u003e= 0", name="ck_order_items_price"),
        CheckConstraint("line_amount \u003e= 0", name="ck_order_items_line"),
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


class Outbox(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        # index on sent_at for efficient querying of unsent events
        # created in migration already, but we could also define here
        # no constraints needed
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)