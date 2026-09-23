"""StockFlow Mini - FastAPI application."""

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from stockflow.database import engine, get_db_session
from stockflow.models import Order, OrderItem, Product
from stockflow.schemas import (
    OrderCreate,
    OrderItemCreate,
    OrderItemResponse,
    OrderResponse,
    ProductCreate,
    ProductResponse,
)

app = FastAPI(title="StockFlow Mini")


# --- Middleware for tenant validation ---

@app.middleware("http")
async def validate_tenant(request: Request, call_next):
    """Validate X-Tenant-Id header and inject into request state."""
    tenant_id_str = request.headers.get("X-Tenant-Id")
    if not tenant_id_str:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_TENANT", "message": "Missing X-Tenant-Id header", "details": {}}},
        )
    try:
        tenant_id = UUID(tenant_id_str)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_TENANT", "message": "Invalid X-Tenant-Id format", "details": {}}},
        )
    request.state.tenant_id = tenant_id
    response = await call_next(request)
    return response


# --- Health check ---

@app.get("/health")
async def health_check():
    """Health check endpoint. Returns 200 only if DB is reachable."""
    try:
        with get_db_session() as db:
            db.execute(select(1))
        return {"status": "ok"}
    except (OperationalError, Exception):
        return JSONResponse(
            status_code=503,
            content={"status": "error"},
        )


# --- Product endpoints ---

@app.post("/products", status_code=201)
async def create_product(product: ProductCreate, request: Request):
    """Create a new product. SKU must be unique per tenant."""
    tenant_id = request.state.tenant_id
    now = datetime.now(timezone.utc)

    with get_db_session() as db:
        # Check for duplicate SKU within the same tenant
        existing = db.execute(
            select(Product).where(
                and_(Product.tenant_id == tenant_id, Product.sku == product.sku)
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "SKU_ALREADY_EXISTS", "message": "SKU already exists for this tenant", "details": {}}},
            )

        product_obj = Product(
            id=uuid4(),
            tenant_id=tenant_id,
            sku=product.sku,
            name=product.name,
            unit_price=product.unit_price,
            stock=product.stock,
            created_at=now,
            updated_at=now,
        )
        db.add(product_obj)
        db.commit()
        db.refresh(product_obj)

        return ProductResponse(
            id=product_obj.id,
            tenant_id=product_obj.tenant_id,
            sku=product_obj.sku,
            name=product_obj.name,
            unit_price=product_obj.unit_price,
            stock=product_obj.stock,
            created_at=product_obj.created_at,
            updated_at=product_obj.updated_at,
        )


@app.get("/products/{product_id}")
async def get_product(product_id: UUID, request: Request):
    """Get a product by ID. Only returns products from the same tenant."""
    tenant_id = request.state.tenant_id

    with get_db_session() as db:
        product = db.execute(
            select(Product).where(
                and_(Product.id == product_id, Product.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

        if not product:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
            )

        return ProductResponse(
            id=product.id,
            tenant_id=product.tenant_id,
            sku=product.sku,
            name=product.name,
            unit_price=product.unit_price,
            stock=product.stock,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )


# --- Order endpoints ---

@app.post("/orders", status_code=201)
async def create_order(order_create: OrderCreate, request: Request):
     """Create an order. Atomic: create order and deduct stock."""
    tenant_id = request.state.tenant_id
    now = datetime.now(timezone.utc)

    with get_db_session() as db:
        try:
            # Validate all products exist and belong to tenant, check stock
            items_data = []
            total_amount = 0

            for item_create in order_create.items:
                product = db.execute(
                    select(Product).where(
                        and_(Product.id == item_create.product_id, Product.tenant_id == tenant_id)
                    )
                ).scalar_one_or_none()

                if not product:
                    raise HTTPException(
                        status_code=404,
                        detail={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
                    )

                if product.stock < item_create.quantity:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": {"code": "INSUFFICIENT_STOCK", "message": f"Insufficient stock for product {product.sku}", "details": {}}},
                    )

                line_amount = product.unit_price * item_create.quantity
                total_amount += line_amount

                items_data.append({
                    "product": product,
                    "quantity": item_create.quantity,
                    "line_amount": line_amount,
                })

            # Deduct stock for all products
            for item_data in items_data:
                product = item_data["product"]
                product.stock -= item_data["quantity"]

            # Create order
            order = Order(
                id=uuid4(),
                tenant_id=tenant_id,
                status="PENDING",
                total_amount=total_amount,
                created_at=now,
                updated_at=now,
            )
            db.add(order)

            # Create order items
            for item_data in items_data:
                product = item_data["product"]
                order_item = OrderItem(
                    id=uuid4(),
                    order_id=order.id,
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    unit_price=product.unit_price,
                    quantity=item_data["quantity"],
                    line_amount=item_data["line_amount"],
                )
                db.add(order_item)

            db.commit()
            db.refresh(order)

            # Fetch order items
            order_items = db.execute(
                select(OrderItem).where(OrderItem.order_id == order.id)
            ).scalars().all()

            return OrderResponse(
                id=order.id,
                tenant_id=order.tenant_id,
                status=order.status,
                total_amount=order.total_amount,
                created_at=order.created_at,
                updated_at=order.updated_at,
                items=[
                    OrderItemResponse(
                        id=item.id,
                        order_id=item.order_id,
                        product_id=item.product_id,
                        sku=item.sku,
                        product_name=item.product_name,
                        unit_price=item.unit_price,
                        quantity=item.quantity,
                        line_amount=item.line_amount,
                    )
                    for item in order_items
                ],
            )

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            # Handle unique constraint violation for stock (shouldn't happen with our logic, but just in case)
            raise HTTPException(
                status_code=500,
                detail={"error": {"code": "INTERNAL_ERROR", "message": str(e), "details": {}}},
            )


@app.get("/orders/{order_id}")
async def get_order(order_id: UUID, request: Request):
     """Get an order by ID with items. Only returns orders from the same tenant."""
    tenant_id = request.state.tenant_id

    with get_db_session() as db:
        order = db.execute(
            select(Order).where(
                and_(Order.id == order_id, Order.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

        if not order:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "NOT_FOUND", "message": "Order not found", "details": {}}},
            )

        order_items = db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        ).scalars().all()

        return OrderResponse(
            id=order.id,
            tenant_id=order.tenant_id,
            status=order.status,
            total_amount=order.total_amount,
            created_at=order.created_at,
            updated_at=order.updated_at,
            items=[
                OrderItemResponse(
                    id=item.id,
                    order_id=item.order_id,
                    product_id=item.product_id,
                    sku=item.sku,
                    product_name=item.product_name,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                    line_amount=item.line_amount,
                )
                for item in order_items
            ],
        )


@app.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: UUID, request: Request):
     """Cancel an order. Only PENDING orders can be cancelled. Atomic: cancel and restore stock."""
    tenant_id = request.state.tenant_id
    now = datetime.now(timezone.utc)

    with get_db_session() as db:
        order = db.execute(
            select(Order).where(
                and_(Order.id == order_id, Order.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()

        if not order:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "NOT_FOUND", "message": "Order not found", "details": {}}},
            )

        if order.status != "PENDING":
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "INVALID_ORDER_STATE", "message": "Order is not in PENDING state", "details": {}}},
            )

        # Restore stock for all order items
        order_items = db.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        ).scalars().all()

        for item in order_items:
            product = db.execute(
                select(Product).where(Product.id == item.product_id)
            ).scalar_one_or_none()

            if product:
                product.stock += item.quantity

        # Update order status
        order.status = "CANCELLED"
        order.updated_at = now

        db.commit()

        return OrderResponse(
            id=order.id,
            tenant_id=order.tenant_id,
            status=order.status,
            total_amount=order.total_amount,
            created_at=order.created_at,
            updated_at=order.updated_at,
            items=[
                OrderItemResponse(
                    id=item.id,
                    order_id=item.order_id,
                    product_id=item.product_id,
                    sku=item.sku,
                    product_name=item.product_name,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                    line_amount=item.line_amount,
                )
                for item in order_items
            ],
        )


# --- Error handlers ---

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
     """Custom HTTP exception handler for consistent error responses."""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc.detail), "details": {}}},
    )
