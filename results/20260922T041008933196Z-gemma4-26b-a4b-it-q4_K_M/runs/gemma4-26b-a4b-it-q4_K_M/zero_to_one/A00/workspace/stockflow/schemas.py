from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from typing import List

class ProductBase(BaseModel):
    sku: str
    name: str
    unit_price: int
    stock: int

class ProductCreate(ProductBase):
    pass

class ProductResponse(ProductBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int

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
