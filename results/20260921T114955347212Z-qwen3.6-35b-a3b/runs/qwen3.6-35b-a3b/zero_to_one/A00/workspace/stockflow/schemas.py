import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    sku: str
    name: str
    unit_price: int
    stock: int


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int


class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int


class OrderCreate(BaseModel):
    items: list[OrderItemCreate]


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]
