from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from uuid import UUID
from .models import Product, Order, OrderItem
from .exceptions import NotFoundException, SkuAlreadyExistsException, InsufficientStockException, InvalidOrderStateException
from collections import defaultdict

def create_product(db: Session, tenant_id: UUID, product_data: any):
    db_product = Product(
        tenant_id=tenant_id,
        sku=product_data.sku,
        name=product_data.name,
        unit_price=product_data.unit_price,
        stock=product_data.stock
    )
    try:
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
        return db_product
    except Exception:
        db.rollback()
        raise SkuAlreadyExistsException()

def get_product(db: Session, tenant_id: UUID, product_id: UUID):
    product = db.execute(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if not product:
        raise NotFoundException()
    return product

def create_order(db: Session, tenant_id: UUID, order_create: any):
    items_map = defaultdict(int)
    for item in order_create.items:
        items_map[item.product_id] += item.quantity

    total_amount = 0
    order_items_to_create = []

    sorted_product_ids = sorted(items_map.keys())

    for product_id in sorted_product_ids:
        quantity = items_map[product_id]
        
        product = db.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id).with_for_update()
        ).scalar_one_or_none()

        if not product:
            # Check if it exists for another tenant to return 404
            exists_elsewhere = db.execute(
                select(Product).where(Product.id == product_id)
            ).scalar_one_or_none()
            if exists_elsewhere:
                raise NotFoundException()
            else:
                raise NotFoundException()

        if product.stock < quantity:
            raise InsufficientStockException()

        line_amount = product.unit_price * quantity
        total_amount += line_amount
        
        order_items_to_create.append({
            "product_id": product.id,
            "sku": product.sku,
            "product_name": product.name,
            "unit_price": product.unit_price,
            "quantity": quantity,
            "line_amount": line_amount
        })
        
        product.stock -= quantity

    new_order = Order(
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=total_amount
    )
    db.add(new_order)
    db.flush()

    for item_data in order_items_to_create:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=item_data["product_id"],
            sku=item_data["sku"],
            product_name=item_data["product_name"],
            unit_price=item_data["unit_price"],
            quantity=item_data["quantity"],
            line_amount=item_data["line_amount"]
        )
        db.add(order_item)

    db.commit()
    db.refresh(new_order)
    return new_order

def get_order(db: Session, tenant_id: UUID, order_id: UUID):
    order = db.execute(
        select(Order)
        .options(joinedload(Order.items))
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
    ).scalar_one_or_none()
    
    if not order:
        raise NotFoundException()
    return order

def cancel_order(db: Session, tenant_id: UUID, order_id: UUID):
    order = db.execute(
        select(Order)
        .options(joinedload(Order.items))
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    
    if not order:
        raise NotFoundException()
    
    if order.status != "PENDING":
        raise InvalidOrderStateException()

    for item in order.items:
        product = db.execute(
            select(Product).where(Product.id == item.product_id).with_for_update()
        ).scalar_one_or_none()
        if product:
            product.stock += item.quantity

    order.status = "CANCELLED"
    db.commit()
    return order
