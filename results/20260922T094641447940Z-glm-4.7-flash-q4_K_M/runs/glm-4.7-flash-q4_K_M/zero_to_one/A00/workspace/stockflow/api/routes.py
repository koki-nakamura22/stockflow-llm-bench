"""API routes."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from stockflow.database import get_db
from stockflow.models import Order, OrderItem, Product, Tenant
from stockflow.schemas import (
    ErrorResponse,
    HealthResponse,
    Order,
    OrderCreate,
    OrderItem,
    OrderItemCreate,
    Product,
    ProductCreate,
)
from stockflow.api.dependencies import (
    get_tenant,
    get_product_or_404,
    get_order_or_404,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(db: Session = Depends(get_db)) -> HealthResponse:
    """Health check endpoint."""
    try:
        db.execute("SELECT 1")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SERVICE_UNAVAILABLE", "message": "Database connection failed"},
        )


@router.post("/products", response_model=Product, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_data: ProductCreate,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant),
) -> Product:
    """Create a new product."""
    # Check for duplicate SKU
    if db.query(Product).filter(
        Product.tenant_id == tenant_id,
        Product.sku == product_data.sku,
    ).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SKU_ALREADY_EXISTS", "message": "SKU already exists"},
        )

    product = Product(
        tenant_id=tenant_id,
        sku=product_data.sku,
        name=product_data.name,
        unit_price=product_data.unit_price,
        stock=product_data.stock,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/products/{product_id}", response_model=Product)
async def get_product(
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant),
) -> Product:
    """Get a product by ID."""
    return await get_product_or_404(db, product_id, tenant_id)


@router.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant),
) -> Order:
    """Create a new order."""
    # Validate all products exist and belong to the same tenant
    items_by_product: dict[uuid.UUID, OrderItemCreate] = {}
    for item in order_data.items:
        if item.product_id in items_by_product:
            # Same product, aggregate quantity
            items_by_product[item.product_id].quantity += item.quantity
        else:
            items_by_product[item.product_id] = item

    # Check stock availability
    for product_id, item in items_by_product.items():
        product = await get_product_or_404(db, product_id, tenant_id)
        if product.stock < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "INSUFFICIENT_STOCK", "message": "Insufficient stock"},
            )

    # Calculate total amount
    total_amount = 0
    for product_id, item in items_by_product.items():
        product = await get_product_or_404(db, product_id, tenant_id)
        total_amount += product.unit_price * item.quantity

    # Create order
    order = Order(
        tenant_id=tenant_id,
        status="PENDING",
        total_amount=total_amount,
    )
    db.add(order)
    db.flush()  # Get order ID

    # Create order items and reduce stock (atomic)
    for product_id, item in items_by_product.items():
        product = await get_product_or_404(db, product_id, tenant_id)
        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            sku=product.sku,
            product_name=product.name,
            unit_price=product.unit_price,
            quantity=item.quantity,
            line_amount=product.unit_price * item.quantity,
        )
        db.add(order_item)

        # Reduce stock
        product.stock -= item.quantity

    db.commit()
    db.refresh(order)

    # Refresh order items
    order_items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    order.items = order_items
    return order


@router.get("/orders/{order_id}", response_model=Order)
async def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant),
) -> Order:
    """Get an order by ID."""
    order = await get_order_or_404(db, order_id, tenant_id)

    # Load order items
    order_items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    order.items = order_items
    return order


@router.post("/orders/{order_id}/cancel", response_model=Order)
async def cancel_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant),
) -> Order:
    """Cancel an order (only PENDING orders)."""
    order = await get_order_or_404(db, order_id, tenant_id)

    if order.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_ORDER_STATE", "message": "Cannot cancel order with current status"},
        )

    # Check if already cancelled
    if order.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_ORDER_STATE", "message": "Order is already cancelled"},
        )

    # Cancel order and restore stock (atomic)
    order.status = "CANCELLED"
    order.updated_at = datetime.now(UTC)

    # Restore stock for each order item
    order_items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    for item in order_items:
        product = await get_product_or_404(db, item.product_id, order.tenant_id)
        product.stock += item.quantity

    db.commit()
    db.refresh(order)

    # Refresh order items
    order_items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    order.items = order_items
    return order