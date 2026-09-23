"""Pydantic schemas for StockFlow Mini."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, PositiveInt, conint

# Product schemas
class ProductCreate(BaseModel):
    sku: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    unit_price: PositiveInt
    stock: PositiveInt

class ProductResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# Order schemas
class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: PositiveInt

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]

class OrderItemResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

    class Config:
        orm_mode = True

class OrderResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]

    class Config:
        orm_mode = True

# Error response
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)

class ErrorResponse(BaseModel):
    error: ErrorDetail

    class Config:
        orm_mode = True
