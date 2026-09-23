from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from uuid import UUID

class ProductBase(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    unit_price: int = Field(..., ge=0)
    stock: int = Field(..., ge=0)

class ProductCreate(ProductBase):
    pass

class ProductResponse(ProductBase):
    id: UUID
    tenant_id: str
    created_at: datetime
    updated_at: datetime

class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(..., gt=0)

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]

class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    product_id: UUID
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

class OrderResponse(BaseModel):
    id: UUID
    tenant_id: str
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}

class ErrorResponse(BaseModel):
    error: ErrorDetail

# For health check
class HealthResponse(BaseModel):
    status: str