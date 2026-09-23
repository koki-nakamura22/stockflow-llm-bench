"""Pydantic schemas for StockFlow Mini API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# Product schemas
class ProductCreate(BaseModel):
    """Request schema for creating a product."""

    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    unit_price: int = Field(..., ge=0)
    stock: int = Field(..., ge=0)


class ProductResponse(BaseModel):
    """Response schema for a product."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Order schemas
class OrderItemCreate(BaseModel):
    """Request schema for an order item."""

    product_id: uuid.UUID
    quantity: int = Field(..., ge=1)


class OrderCreate(BaseModel):
    """Request schema for creating an order."""

    items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItemResponse(BaseModel):
    """Response schema for an order item."""

    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    """Response schema for an order."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


# Error schemas
class ErrorDetail(BaseModel):
    """Generic error response schema."""

    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Error response wrapper."""

    error: ErrorDetail
