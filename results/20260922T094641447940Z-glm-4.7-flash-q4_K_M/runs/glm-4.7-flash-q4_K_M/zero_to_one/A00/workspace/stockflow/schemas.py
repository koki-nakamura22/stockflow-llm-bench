"""Pydantic schemas for request/response validation."""
from datetime import datetime

from pydantic import UUID4, BaseModel, Field, field_validator


class BaseProduct(BaseModel):
    """Base product schema."""

    sku: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    unit_price: int = Field(..., gt=0)
    stock: int = Field(..., ge=0)


class ProductCreate(BaseProduct):
    """Product creation schema."""

    pass


class Product(BaseProduct):
    """Product response schema."""

    id: UUID4
    tenant_id: UUID4
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrderItemCreate(BaseModel):
    """Order item creation schema."""

    product_id: UUID4
    quantity: int = Field(..., gt=0)


class OrderCreate(BaseModel):
    """Order creation schema."""

    items: list[OrderItemCreate] = Field(..., min_length=1)


class OrderItem(BaseModel):
    """Order item response schema."""

    id: UUID4
    order_id: UUID4
    product_id: UUID4
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int


class Order(BaseModel):
    """Order response schema."""

    id: UUID4
    tenant_id: UUID4
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItem] = []


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: dict[str, str]