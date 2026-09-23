import uuid
import hashlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    unit_price: int = Field(ge=0)
    stock: int = Field(ge=0)


class ProductOut(ProductCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        # ASCII 1-128 characters
        if not v or len(v) < 1 or len(v) > 128:
            raise ValueError("Idempotency key must be 1-128 ASCII characters")
        # Check if all characters are ASCII (1-127)
        if any(ord(c) > 127 for c in v):
            raise ValueError("Idempotency key must be ASCII characters only")
        return v


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_price: int
    quantity: int
    line_amount: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    total_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]

