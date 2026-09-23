"""Product CRUD router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from stockflow.database import get_db
from stockflow.deps import get_tenant_id
from stockflow.models import Product
from stockflow.schemas import ProductCreate, ProductResponse

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Create a new product. SKU must be unique within the tenant."""
    # Check if SKU already exists for this tenant
    existing = db.execute(
        select(Product).where(
            Product.tenant_id == tenant_id,
            Product.sku == payload.sku,
        )
    ).scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "SKU_ALREADY_EXISTS",
                    "message": f"SKU '{payload.sku}' already exists for this tenant",
                    "details": {"sku": payload.sku},
                }
            },
        )

    product = Product(
        tenant_id=tenant_id,
        sku=payload.sku,
        name=payload.name,
        unit_price=payload.unit_price,
        stock=payload.stock,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Get a product by ID. Only returns products belonging to the tenant."""
    product = (
        db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == tenant_id,
            )
        )
        .scalars()
        .first()
    )

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Product '{product_id}' not found",
                    "details": {"product_id": str(product_id)},
                }
            },
        )

    return product
