"""Pydantic schemas for StockFlow Mini."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- Product schemas ---

class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1)
    unit_price: int = Field(..., ge=0)
    stock: int = Field(..., ge=0)


class ProductResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    sku: str
    name: str
    unit_price: int
    stock: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Order schemas ---

class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(..., ge=1)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    product_id: UUID
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


# --- Error schema ---

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail

    model_config = {"from_attributes": True}
