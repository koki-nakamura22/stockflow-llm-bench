"""Order router for StockFlow Mini."""
import uuid
from datetime import datetime
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError

from .db import SessionLocal
from .models import Product, Order, OrderItem
from .schemas import OrderCreate, OrderOut, OrderItemOut
from .dependencies import get_tenant_id

router = APIRouter(prefix="/orders", tags=["orders"])

# DB session dependency
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper to format error

def error_response(code: str, message: str):
    return {"error": {"code": code, "message": message, "details": {}}}

@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    # Aggregate quantities by product_id
    agg = defaultdict(int)
    for item in payload.items:
        agg[item.product_id] += item.quantity

    # Fetch products with FOR UPDATE to lock rows
    product_ids = list(agg.keys())
    stmt = select(Product).where(Product.id.in_(product_ids), Product.tenant_id == tenant_id).with_for_update()
    result = db.execute(stmt)
    products = result.scalars().all()
    if len(products) != len(product_ids):
        # missing product or wrong tenant
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_response("NOT_FOUND", "Product not found"))

    # Check stock
    for prod in products:
        if prod.stock < agg[prod.id]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_response("INSUFFICIENT_STOCK", "Insufficient stock"))

    # Create order
    order = Order(tenant_id=tenant_id, status="PENDING", total_amount=0)
    db.add(order)
    db.flush()  # get order.id

    total_amount = 0
    for prod in products:
        qty = agg[prod.id]
        line_amount = prod.unit_price * qty
        total_amount += line_amount
        # Deduct stock
        prod.stock -= qty
        # Create order item snapshot
        item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            sku=prod.sku,
            product_name=prod.name,
            unit_price=prod.unit_price,
            quantity=qty,
            line_amount=line_amount,
        )
        db.add(item)
    order.total_amount = total_amount
    db.commit()
    db.refresh(order)
    return order

@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    stmt = select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    result = db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_response("NOT_FOUND", "Order not found"))
    # Load items
    order.items  # accessed to load
    return order

@router.post("/{order_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    stmt = select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id).with_for_update()
    result = db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_response("NOT_FOUND", "Order not found"))
    if order.status != "PENDING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_response("INVALID_ORDER_STATE", "Order cannot be cancelled"))
    # Restore stock
    for item in order.items:
        prod = db.get(Product, item.product_id)
        if prod:
            prod.stock += item.quantity
    order.status = "CANCELLED"
    db.commit()
    return {"status": "cancelled"}
