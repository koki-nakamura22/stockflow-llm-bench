"""Pydantic schemas for StockFlow API."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Request schemas

class ProductCreateRequest(BaseModel):
    sku: str = Field(..., description="Stock Keeping Unit")
    name: str = Field(..., description="Product name")
    unit_price: int = Field(..., ge=0, description="Unit price in yen")
    stock: int = Field(..., ge=0, description="Available stock")

class OrderItemRequest(BaseModel):
    product_id: UUID = Field(..., description="Product ID")
    quantity: int = Field(..., gt=0, description="Quantity requested")

class OrderCreateRequest(BaseModel):
    items: List[OrderItemRequest] = Field(..., description="List of order items")

# Response schemas

class ProductResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    product_id: UUID
    sku: str

    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

    class Config:
        from_attributes = True

class OrderResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]

    class Config:
        from_attributes = True

# Error response schema (internal usage)

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}