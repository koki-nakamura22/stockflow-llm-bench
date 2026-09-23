"""Pydantic schemas for StockFlow Mini."""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, PositiveInt, conint

# Product schemas
class ProductCreate(BaseModel):
    sku: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    unit_price: conint(ge=0) = Field(...)
    stock: PositiveInt = Field(...)

class ProductOut(BaseModel):
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

class OrderItemOut(BaseModel):
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

class OrderOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemOut]

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
