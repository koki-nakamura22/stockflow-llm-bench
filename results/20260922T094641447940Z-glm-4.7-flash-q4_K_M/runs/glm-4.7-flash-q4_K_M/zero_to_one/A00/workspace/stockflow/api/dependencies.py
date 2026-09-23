"""API dependencies."""
import uuid

from fastapi import Depends, HTTPException, status

from stockflow.database import get_db
from stockflow.models import Order, Product, Tenant


async def get_tenant(tenant_id: str) -> uuid.UUID:
    """Get tenant by ID."""
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_TENANT", "message": "X-Tenant-Id header is required"},
        )
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_TENANT", "message": "Invalid tenant ID format"},
        )
    return tenant_uuid


async def get_product_or_404(db: Session, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Product:
    """Get product by ID or raise 404."""
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.tenant_id == tenant_id,
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Product not found"},
        )
    return product


async def get_order_or_404(db: Session, order_id: uuid.UUID, tenant_id: uuid.UUID) -> Order:
    """Get order by ID or raise 404."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.tenant_id == tenant_id,
    ).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Order not found"},
        )
    return order