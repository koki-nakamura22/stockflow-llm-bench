from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UUID, BigInteger, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    
    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(String, nullable=False)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    unit_price = Column(Integer, nullable=False)
    stock = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_products_tenant_id', 'tenant_id'),
        Index('ix_products_sku_tenant_id', 'sku', 'tenant_id', unique=True),
    )

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(String, nullable=False)
    status = Column(String, nullable=False)  # PENDING, CANCELLED
    total_amount = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_orders_tenant_id', 'tenant_id'),
    )

class OrderItem(Base):
    __tablename__ = "order_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    sku = Column(String, nullable=False)
    product_name = Column(String, nullable=False)
    unit_price = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Integer, nullable=False)
    
    order = relationship("Order", back_populates="items")
    
    __table_args__ = (
        Index('ix_order_items_order_id', 'order_id'),
        Index('ix_order_items_product_id', 'product_id'),
    )

# Configure relationships
Order.items = relationship("OrderItem", back_populates="order")