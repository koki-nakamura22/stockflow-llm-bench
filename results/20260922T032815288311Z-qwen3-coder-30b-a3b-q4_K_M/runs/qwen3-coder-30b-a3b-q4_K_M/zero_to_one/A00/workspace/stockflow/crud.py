from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID
import uuid
from .models import Product, Order, OrderItem
from .schemas import ProductCreate, OrderCreate
from .exceptions import (
    SKUAlreadyExistsException, 
    ProductNotFoundException, 
    InsufficientStockException,
    InvalidOrderStateException
)
from .database import Base

def create_product(db: Session, product: ProductCreate, tenant_id: str) -> Product:
    db_product = Product(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        sku=product.sku,
        name=product.name,
        unit_price=product.unit_price,
        stock=product.stock
    )
    
    try:
        db.add(db_product)
        db.commit()
        db.refresh(db_product)
        return db_product
    except IntegrityError:
        db.rollback()
        raise SKUAlreadyExistsException()

def get_product(db: Session, product_id: UUID, tenant_id: str) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.tenant_id == tenant_id
    ).first()
    
    if not product:
        raise ProductNotFoundException()
    
    return product

def get_product_by_sku(db: Session, sku: str, tenant_id: str) -> Product:
    product = db.query(Product).filter(
        Product.sku == sku,
        Product.tenant_id == tenant_id
    ).first()
    
    if not product:
        raise ProductNotFoundException()
    
    return product

def get_all_products(db: Session, tenant_id: str) -> list[Product]:
    return db.query(Product).filter(Product.tenant_id == tenant_id).all()

def update_product_stock(db: Session, product_id: UUID, quantity: int) -> Product:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
    
    if not product:
        raise ProductNotFoundException()
        
    new_stock = product.stock - quantity
    if new_stock < 0:
        raise InsufficientStockException()
        
    product.stock = new_stock
    db.commit()
    db.refresh(product)
    return product

def create_order(db: Session, order_create: OrderCreate, tenant_id: str) -> Order:
    # First, validate all products exist and collect their details
    product_details = {}
    total_amount = 0
    
    # Group items by product_id to sum quantities
    item_groups = {}
    for item in order_create.items:
        if item.product_id in item_groups:
            item_groups[item.product_id] += item.quantity
        else:
            item_groups[item.product_id] = item.quantity
    
    # Fetch all products at once to prevent race conditions
    product_ids = list(item_groups.keys())
    products = db.query(Product).filter(Product.id.in_(product_ids)).with_for_update().all()
    
    # Create a mapping of product IDs to product objects
    product_map = {p.id: p for p in products}
    
    order_items = []
    for product_id, quantity in item_groups.items():
        if product_id not in product_map:
            raise ProductNotFoundException()
            
        product = product_map[product_id]
        
        # Store product details for order items
        product_details[product_id] = {
            'sku': product.sku,
            'name': product.name,
            'unit_price': product.unit_price
        }
        
        line_amount = product.unit_price * quantity
        total_amount += line_amount
        
        order_items.append({
            'id': uuid.uuid4(),
            'product_id': product_id,
            'sku': product.sku,
            'product_name': product.name,
            'unit_price': product.unit_price,
            'quantity': quantity,
            'line_amount': line_amount
        })
    
    # Create the order
    db_order = Order(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=total_amount
    )
    
    db.add(db_order)
    
    # Create order items and update stock
    for item in order_items:
        db_item = OrderItem(**item, order_id=db_order.id)
        db.add(db_item)
        
        # Update product stock
        product = product_map[item['product_id']]
        product.stock -= item['quantity']
    
    db.commit()
    db.refresh(db_order)
    
    return db_order

def get_order(db: Session, order_id: UUID, tenant_id: str) -> Order:
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.tenant_id == tenant_id
    ).first()
    
    if not order:
        raise OrderNotFoundException()
        
    return order

def cancel_order(db: Session, order_id: UUID, tenant_id: str) -> Order:
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.tenant_id == tenant_id
    ).with_for_update().first()
    
    if not order:
        raise OrderNotFoundException()
        
    if order.status != "PENDING":
        raise InvalidOrderStateException()
        
    # Restore stock for all items in this order
    order_items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    
    for item in order_items:
        product = db.query(Product).filter(Product.id == item.product_id).with_for_update().first()
        if product:
            product.stock += item.quantity
    
    # Cancel the order
    order.status = "CANCELLED"
    db.commit()
    db.refresh(order)
    
    return order

def get_order_with_items(db: Session, order_id: UUID, tenant_id: str) -> Order:
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.tenant_id == tenant_id
    ).first()
    
    if not order:
        raise OrderNotFoundException()
        
    return order