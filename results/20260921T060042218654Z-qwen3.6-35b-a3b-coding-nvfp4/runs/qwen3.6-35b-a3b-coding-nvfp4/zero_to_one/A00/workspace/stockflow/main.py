"""StockFlow Mini - Stock and Order Management API."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from stockflow.database import get_db
from stockflow.models import Base, Order, OrderItem, Product
from stockflow.schemas import (
    OrderCreate,
    OrderItemCreate,
    OrderItemResponse,
    OrderResponse,
    ProductCreate,
    ProductResponse,
)

from fastapi import FastAPI

app = FastAPI(title="StockFlow Mini")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_tenant(tenant_id: str | None) -> str:
    """Validate that tenant_id is a valid UUID."""
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TENANT",
                    "message": "Invalid or missing X-Tenant-Id header",
                    "details": {},
                }
            },
        )
    try:
        uuid.UUID(tenant_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TENANT",
                    "message": "Invalid or missing X-Tenant-Id header",
                    "details": {},
                }
            },
        )
    return tenant_id


def _not_found(resource_type: str, resource_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": {
                "code": "NOT_FOUND",
                "message": f"{resource_type} not found",
                "details": {"id": resource_id},
            }
        },
    )


def _error_response(code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Health check - returns 200 only when DB connection is available."""
    try:
        db.execute(select(1))
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "DB_UNAVAILABLE", "message": "Database connection failed", "details": {}}},
        )


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(
    body: ProductCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Create a product. SKU must be unique per tenant."""
    tenant_id = _validate_tenant(x_tenant_id)

    # Check for duplicate SKU within the same tenant
    existing = db.execute(
        select(Product).where(
            Product.tenant_id == uuid.UUID(tenant_id),
            Product.sku == body.sku,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise _error_response(
            "SKU_ALREADY_EXISTS",
            f"SKU '{body.sku}' already exists for this tenant",
            {"sku": body.sku},
        )

    product = Product(
        tenant_id=uuid.UUID(tenant_id),
        sku=body.sku,
        name=body.name,
        unit_price=body.unit_price,
        stock=body.stock,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/products/{product_id}")
def get_product(
    product_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Get a product by ID. Only returns products belonging to the tenant."""
    tenant_id = _validate_tenant(x_tenant_id)

    try:
        pid = uuid.UUID(product_id)
    except (ValueError, AttributeError):
        raise _not_found("Product", product_id)

    product = db.execute(
        select(Product).where(
            Product.id == pid,
            Product.tenant_id == uuid.UUID(tenant_id),
        )
    ).scalar_one_or_none()

    if product is None:
        raise _not_found("Product", product_id)

    return product


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    body: OrderCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Create an order. Atomic: create order and deduct stock."""
    tenant_id = _validate_tenant(x_tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)

    # Validate all items first
    if not body.items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Order must have at least one item",
                    "details": {},
                }
            },
        )

    # Collect all product IDs and validate they exist and belong to tenant
    product_map: dict[uuid.UUID, Product] = {}
    for item in body.items:
        try:
            pid = uuid.UUID(item.product_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": f"Invalid product_id: {item.product_id}",
                        "details": {"product_id": item.product_id},
                    }
                },
            )

        product = db.execute(
            select(Product).where(
                Product.id == pid,
                Product.tenant_id == tenant_uuid,
            )
        ).scalar_one_or_none()

        if product is None:
            raise _not_found("Product", item.product_id)

        product_map[pid] = product

    # Aggregate quantities per product
    aggregated: dict[uuid.UUID, int] = {}
    for item in body.items:
        pid = uuid.UUID(item.product_id)
        aggregated[pid] = aggregated.get(pid, 0) + item.quantity

    # Check stock availability for all products
    for pid, qty in aggregated.items():
        product = product_map[pid]
        if product.stock < qty:
            raise _error_response(
                "INSUFFICIENT_STOCK",
                f"Insufficient stock for product '{product.sku}'",
                {"product_id": str(pid), "requested": qty, "available": product.stock},
            )

    # Calculate total amount
    total_amount = 0
    for pid, qty in aggregated.items():
        product = product_map[pid]
        total_amount += product.unit_price * qty

    # Create order
    order = Order(
        tenant_id=tenant_uuid,
        status="PENDING",
        total_amount=total_amount,
    )
    db.add(order)
    db.flush()  # Get order.id

    # Create order items
    order_items: list[OrderItem] = []
    for item in body.items:
        pid = uuid.UUID(item.product_id)
        product = product_map[pid]
        line_amount = product.unit_price * item.quantity
        oi = OrderItem(
            order_id=order.id,
            product_id=pid,
            sku=product.sku,
            product_name=product.name,
            unit_price=product.unit_price,
            quantity=item.quantity,
            line_amount=line_amount,
        )
        order_items.append(oi)
        db.add(oi)

    # Deduct stock
    for pid, qty in aggregated.items():
        product = product_map[pid]
        product.stock -= qty

    db.commit()
    db.refresh(order)

    return order


@app.get("/orders/{order_id}")
def get_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Get an order by ID with items. Only returns orders belonging to the tenant."""
    tenant_id = _validate_tenant(x_tenant_id)

    try:
        oid = uuid.UUID(order_id)
    except (ValueError, AttributeError):
        raise _not_found("Order", order_id)

    order = db.execute(
        select(Order).where(
            Order.id == oid,
            Order.tenant_id == uuid.UUID(tenant_id),
        )
    ).scalar_one_or_none()

    if order is None:
        raise _not_found("Order", order_id)

    return order


@app.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Cancel an order. Only PENDING orders can be cancelled. Atomic: cancel and restore stock."""
    tenant_id = _validate_tenant(x_tenant_id)

    try:
        oid = uuid.UUID(order_id)
    except (ValueError, AttributeError):
        raise _not_found("Order", order_id)

    tenant_uuid = uuid.UUID(tenant_id)

    order = db.execute(
        select(Order).where(
            Order.id == oid,
            Order.tenant_id == tenant_uuid,
        )
    ).scalar_one_or_none()

    if order is None:
        raise _not_found("Order", order_id)

    if order.status != "PENDING":
        raise _error_response(
            "INVALID_ORDER_STATE",
            f"Order is not in PENDING state (current: {order.status})",
            {"order_id": str(order_id), "status": order.status},
        )

    # Restore stock for all order items
    items = db.execute(
        select(OrderItem).where(OrderItem.order_id == oid)
    ).scalars().all()

    for item in items:
        product = db.execute(
            select(Product).where(
                Product.id == item.product_id,
                Product.tenant_id == tenant_uuid,
            )
        ).scalar_one_or_none()
        if product is None:
            # This shouldn't happen in normal flow, but handle gracefully
            raise _not_found("Product", str(item.product_id))
        product.stock += item.quantity

    order.status = "CANCELLED"
    order.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(order)

    return order


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.exception_handler(ValidationError)
async def validation_error_handler(request, exc: ValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation error",
                "details": {
                    "errors": [
                        {"field": e.get("loc", [""])[-1] if e.get("loc") else "", "message": e.get("msg", "")}
                        for e in exc.errors()
                    ]
                },
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc.detail), "details": {}}},
    )
