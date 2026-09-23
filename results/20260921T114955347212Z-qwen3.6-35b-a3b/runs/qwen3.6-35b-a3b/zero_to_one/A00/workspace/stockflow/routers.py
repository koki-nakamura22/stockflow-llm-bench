import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from stockflow.database import get_db
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import OrderCreate, OrderItemCreate, OrderResponse, ProductCreate, ProductResponse

router = APIRouter()


def _get_tenant_id(x_tenant_id: str | None = Header(...)) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail={"error": {"code": "INVALID_TENANT", "message": "Invalid tenant ID", "details": {}}})


def _tenant_header(tenant_id: uuid.UUID = Depends(_get_tenant_id)) -> uuid.UUID:
    return tenant_id


# ── Products ──────────────────────────────────────────────────────────────


@router.post("/products", status_code=201)
def create_product(
    body: ProductCreate,
    tenant_id: uuid.UUID = Depends(_tenant_header),
    db: Session = Depends(get_db),
) -> ProductResponse:
    # Check for duplicate SKU within tenant
    existing = db.execute(
        select(Product).where(Product.tenant_id == tenant_id, Product.sku == body.sku)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "SKU_ALREADY_EXISTS", "message": f"SKU '{body.sku}' already exists", "details": {}}},
        )

    product = Product(
        tenant_id=tenant_id,
        sku=body.sku,
        name=body.name,
        unit_price=body.unit_price,
        stock=body.stock,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products/{product_id}")
def get_product(
    product_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_tenant_header),
    db: Session = Depends(get_db),
) -> ProductResponse:
    product = db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
        )
    return product


# ── Orders ────────────────────────────────────────────────────────────────


@router.post("/orders", status_code=201)
def create_order(
    body: OrderCreate,
    tenant_id: uuid.UUID = Depends(_tenant_header),
    db: Session = Depends(get_db),
) -> OrderResponse:
    if not body.items:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "VALIDATION_ERROR", "message": "Items must not be empty", "details": {}}},
        )

    # Fetch products and validate
    product_ids = [item.product_id for item in body.items]
    products = db.execute(
        select(Product).where(Product.id.in_(product_ids), Product.tenant_id == tenant_id)
    ).scalars().all()

    product_map = {p.id: p for p in products}

    # Check all products exist in tenant
    for item in body.items:
        if item.product_id not in product_map:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "NOT_FOUND", "message": f"Product {item.product_id} not found", "details": {}}},
            )

    # Aggregate quantities per product
    aggregated: dict[uuid.UUID, int] = {}
    for item in body.items:
        aggregated[item.product_id] = aggregated.get(item.product_id, 0) + item.quantity

    # Check stock for each product
    for product_id, qty in aggregated.items():
        product = product_map[product_id]
        if product.stock < qty:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "INSUFFICIENT_STOCK", "message": f"Insufficient stock for product {product_id}", "details": {}}},
            )

    # Create order and items
    order = Order(tenant_id=tenant_id, status="PENDING", total_amount=0)
    db.add(order)
    db.flush()  # Get order.id

    total_amount = 0
    items_created: list[OrderItem] = []

    for item in body.items:
        product = product_map[item.product_id]
        line_amount = product.unit_price * item.quantity
        total_amount += line_amount

        order_item = OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            sku=product.sku,
            product_name=product.name,
            unit_price=product.unit_price,
            quantity=item.quantity,
            line_amount=line_amount,
        )
        items_created.append(order_item)
        db.add(order_item)

    # Update stock atomically with SELECT FOR UPDATE
    for product_id, qty in aggregated.items():
        product = product_map[product_id]
        product.stock -= qty

    order.total_amount = total_amount
    order.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(order)

    # Re-fetch with eager loading
    result = db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items))
    ).scalar_one_or_none()

    return result


@router.get("/orders/{order_id}")
def get_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_tenant_header),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Order not found", "details": {}}},
        )
    return order


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(_tenant_header),
    db: Session = Depends(get_db),
) -> OrderResponse:
    order = db.execute(
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .options(selectinload(Order.items))
        .with_for_update()
    ).scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Order not found", "details": {}}},
        )

    if order.status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "INVALID_ORDER_STATE", "message": f"Order is in state '{order.status}'", "details": {}}},
        )

    # Restore stock
    for item in order.items:
        product = db.execute(
            select(Product)
            .where(Product.id == item.product_id, Product.tenant_id == tenant_id)
            .with_for_update()
        ).scalar_one_or_none()
        if product is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
            )
        product.stock += item.quantity

    order.status = "CANCELLED"
    order.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(order)

    # Re-fetch with eager loading
    result = db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items))
    ).scalar_one_or_none()

    return result
