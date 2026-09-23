import os
import uuid
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://stockflow:stockflow@db:5432/stockflow"
)

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)

Base = declarative_base()

class TenantMixin:
    # we store tenant_id as UUID
    tenant_id = Column(UUID(as_uuid=True), nullable=False)

class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.utcnow, nullable=False)

class Product(TenantMixin, TimestampMixin, Base):
    __tablename__ = "products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    unit_price = Column(Integer, nullable=False)
    stock = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint('tenant_id', 'sku', name='uq_products_tenant_sku'),)

class Order(TenantMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(String(20), nullable=False, default="PENDING")
    total_amount = Column(Integer, nullable=False, default=0)
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(TenantMixin, TimestampMixin, Base):
    __tablename__ = "order_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)
    sku = Column(String(100), nullable=False)
    product_name = Column(String(200), nullable=False)
    unit_price = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
