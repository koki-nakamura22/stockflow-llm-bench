"""StockFlow Mini Pydantic schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    unit_price: int = Field(..., ge=0)
    stock: int = Field(..., ge=0)


class ProductResponse(BaseModel):
    id: str
    tenant_id: str
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(..., ge=1)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItemResponse(BaseModel):
    id: str
    order_id: str
    product_id: str
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: str
    tenant_id: str
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse] = []

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    error: dict[str, Any]
