"""API routers for products and orders."""
from __future__ import annotations

import uuid
from datetime import datetime
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select, update, func

from . import schemas, database
from .dependencies import get_tenant_id, get_db_session

router = APIRouter()

# Helper to build error response
class APIError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}

# Product endpoints
@router.post("/products", response_model=schemas.ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: schemas.ProductCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db_session),
):
    # Check duplicate SKU
    stmt = select(database.Product).where(
        database.Product.tenant_id == tenant_id, database.Product.sku == payload.sku
    )
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        raise APIError("SKU_ALREADY_EXISTS", "SKU already exists for this tenant")
    product = database.Product(
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

@router.get("/products/{product_id}", response_model=schemas.ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db_session),
):
    stmt = select(database.Product).where(
        database.Product.id == product_id, database.Product.tenant_id == tenant_id
    )
    product = db.execute(stmt).scalar_one_or_none()
    if not product:
        raise APIError("NOT_FOUND", "Product not found")
    return product

# Order endpoints
@router.post("/orders", response_model=schemas.OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: schemas.OrderCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db_session),
):
    # Aggregate quantities
    qty_map: dict[uuid.UUID, int] = defaultdict(int)
    for item in payload.items:
        qty_map[item.product_id] += item.quantity
    # Fetch products
    product_ids = list(qty_map.keys())
    stmt = select(database.Product).where(
        database.Product.id.in_(product_ids), database.Product.tenant_id == tenant_id
    )
    products = db.execute(stmt).scalars().all()
    if len(products) != len(product_ids):
        raise APIError("NOT_FOUND", "One or more products not found")
    # Check stock
    for prod in products:
        if prod.stock < qty_map[prod.id]:
            raise APIError("INSUFFICIENT_STOCK", f"Insufficient stock for product {prod.sku}")
    # Begin transaction
    try:
        # Deduct stock
        for prod in products:
            prod.stock -= qty_map[prod.id]
            db.add(prod)
        # Create order
        order = database.Order(
            tenant_id=tenant_id,
            status="PENDING",
            total_amount=0,
        )
        db.add(order)
        db.flush()  # get order.id
        total = 0
        order_items = []
        for prod in products:
            qty = qty_map[prod.id]
            line_amount = prod.unit_price * qty
            total += line_amount
            item = database.OrderItem(
                order_id=order.id,
                product_id=prod.id,
                sku=prod.sku,
                product_name=prod.name,
                unit_price=prod.unit_price,
                quantity=qty,
                line_amount=line_amount,
            )
            db.add(item)
            order_items.append(item)
        order.total_amount = total
        db.commit()
        db.refresh(order)
        # Load items
        order.items = order_items
        return order
    except Exception as e:
        db.rollback()
        raise e

@router.get("/orders/{order_id}", response_model=schemas.OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db_session),
):
    stmt = select(database.Order).where(
        database.Order.id == order_id, database.Order.tenant_id == tenant_id
    )
    order = db.execute(stmt).scalar_one_or_none()
    if not order:
        raise APIError("NOT_FOUND", "Order not found")
    # Load items
    stmt_items = select(database.OrderItem).where(database.OrderItem.order_id == order.id)
    items = db.execute(stmt_items).scalars().all()
    order.items = items
    return order

@router.post("/orders/{order_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db_session),
):
    stmt = select(database.Order).where(
        database.Order.id == order_id, database.Order.tenant_id == tenant_id
    )
    order = db.execute(stmt).scalar_one_or_none()
    if not order:
        raise APIError("NOT_FOUND", "Order not found")
    if order.status != "PENDING":
        raise APIError("INVALID_ORDER_STATE", "Only pending orders can be cancelled")
    # Begin transaction
    try:
        # Restore stock
        stmt_items = select(database.OrderItem).where(database.OrderItem.order_id == order.id)
        items = db.execute(stmt_items).scalars().all()
        for item in items:
            prod = db.get(database.Product, item.product_id)
            if prod:
                prod.stock += item.quantity
                db.add(prod)
        order.status = "CANCELLED"
        db.add(order)
        db.commit()
        return {"message": "Order cancelled"}
    except Exception as e:
        db.rollback()
        raise e
