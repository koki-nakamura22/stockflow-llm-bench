import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class IdempotencyKeyHeader(BaseModel):
    key: str = Field(min_length=1, max_length=128)

    def validate_key(self) -> str:
        if not all(32 <= ord(c) <= 126 for c in self.key):
            raise ValueError("Idempotency-Key must contain only ASCII printable characters")
        return self.key

    model_config = ConfigDict(validate_assignment=True)


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

