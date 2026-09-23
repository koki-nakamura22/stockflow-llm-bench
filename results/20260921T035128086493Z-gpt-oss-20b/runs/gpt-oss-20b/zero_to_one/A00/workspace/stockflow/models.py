"""SQLAlchemy models for StockFlow Mini."""
import uuid
from datetime import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, Enum, UniqueConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .db import Base

class Product(Base):
    __tablename__ = "products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    unit_price = Column(Integer, nullable=False)
    stock = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_tenant_sku"),)

    items = relationship("OrderItem", back_populates="product")

class Order(Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING")
    total_amount = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    sku = Column(String(255), nullable=False)
    product_name = Column(String(255), nullable=False)
    unit_price = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="items")

# Ensure tables are created
from .db import engine
Base.metadata.create_all(bind=engine)
