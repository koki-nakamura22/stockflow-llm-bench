import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from stockflow.models import Order


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
    subtotal_amount: int
    tax_amount: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]

    @computed_field
    @property
    def total_amount(self) -> int:
        return self.subtotal_amount + self.tax_amount


def order_to_out(order: Order) -> OrderOut:
    """Build an OrderOut from an Order ORM instance.

    During the compatibility window the physical `total_amount` column still
    stores the tax-exclusive subtotal (preserved for the legacy app). The
    tax-inclusive total is surfaced by the API via the computed property
    above; this helper exists so callers can construct the response object
    deterministically without relying on from_attributes resolution order.
    """
    return OrderOut(
        id=order.id,
        tenant_id=order.tenant_id,
        status=order.status,
        subtotal_amount=order.subtotal_amount,
        tax_amount=order.tax_amount,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            OrderItemOut(
                id=item.id,
                order_id=item.order_id,
                product_id=item.product_id,
                sku=item.sku,
                product_name=item.product_name,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_amount=item.line_amount,
            )
            for item in order.items
        ],
    )
