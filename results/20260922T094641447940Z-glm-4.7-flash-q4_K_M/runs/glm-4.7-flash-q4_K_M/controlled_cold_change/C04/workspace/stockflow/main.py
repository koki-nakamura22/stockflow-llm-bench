import argparse
import json
import os
import uuid
from collections import defaultdict
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from stockflow.db import get_session, claim_outbox_events, mark_outbox_sent, mark_outbox_failed
from stockflow.models import Order, OrderItem, Product, Outbox
from stockflow.schemas import OrderCreate, OrderOut, ProductCreate, ProductOut, OutboxEntryCreate

app = FastAPI(title="StockFlow Mini")


def publish_event(event_type: str, payload: dict) -> None:
    """At-least-once delivery to EVENT_PUBLISH_URL"""
    url = os.environ.get("EVENT_PUBLISH_URL", "http://localhost:8080/events")
    response = requests.post(
        url,
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4()), "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()


def run_outbox_worker_once() -> None:
    """Process a single batch of outbox events"""
    from stockflow.db import SessionLocal

    session = SessionLocal()
    try:
        events = claim_outbox_events(session)
        if not events:
            print("No events to process")
            return

        event_ids = [e.id for e in events]
        for event in events:
            try:
                publish_event(event.event_type, json.loads(event.payload))
                mark_outbox_sent(session, event_ids)
                print(f"Published event {event.event_id} ({event.event_type})")
            except Exception as exc:
                mark_outbox_failed(session, event_ids, str(exc))
                print(f"Failed to publish event {event.event_id}: {exc}")

        session.commit()
    finally:
        session.close()


@app.post("/outbox", response_model=OutboxEntryCreate)
def create_outbox_entry(
    entry: OutboxEntryCreate,
    session: Session = Depends(get_session),
) -> Outbox:
    """Transactional outbox: add event entry in the same transaction"""
    outbox_entry = Outbox(
        event_id=uuid.uuid4(),
        event_type=entry.event_type,
        aggregate_id=entry.aggregate_id,
        payload=json.dumps(entry.payload),
    )
    session.add(outbox_entry)
    return outbox_entry


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


@app.exception_handler(ApiError)
def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status, content=error_body(exc.code, exc.message, exc.details)
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body("VALIDATION_ERROR", "Invalid request", {"errors": exc.errors()}),
    )


def tenant_id(x_tenant_id: str | None = Header(default=None)) -> uuid.UUID:
    try:
        if x_tenant_id is None:
            raise ValueError
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise ApiError(400, "INVALID_TENANT", "X-Tenant-Id must be a UUID") from exc


def load_order(session: Session, tenant: uuid.UUID, order_id: uuid.UUID, lock: bool = False) -> Order:
    stmt = (
        select(Order)
        .where(Order.id == order_id, Order.tenant_id == tenant)
        .options(selectinload(Order.items))
    )
    if lock:
        stmt = stmt.with_for_update()
    order = session.scalar(stmt)
    if order is None:
        raise ApiError(404, "NOT_FOUND", "Order not found")
    return order


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/products", response_model=ProductOut, status_code=201)
def create_product(
    body: ProductCreate,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Product:
    product = Product(tenant_id=tenant, **body.model_dump())
    session.add(product)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(409, "SKU_ALREADY_EXISTS", "SKU already exists") from exc
    session.refresh(product)
    return product


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Product:
    product = session.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant)
    )
    if product is None:
        raise ApiError(404, "NOT_FOUND", "Product not found")
    return product


@app.post("/orders", response_model=OrderOut, status_code=201)
def create_order(
    body: OrderCreate,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Order:
    quantities: dict[uuid.UUID, int] = defaultdict(int)
    for item in body.items:
        quantities[item.product_id] += item.quantity
    product_ids = sorted(quantities, key=str)
    try:
        products = list(
            session.scalars(
                select(Product)
                .where(Product.id.in_(product_ids), Product.tenant_id == tenant)
                .order_by(Product.id)
                .with_for_update()
            )
        )
        if len(products) != len(product_ids):
            raise ApiError(404, "NOT_FOUND", "Product not found")
        for product in products:
            if product.stock < quantities[product.id]:
                raise ApiError(409, "INSUFFICIENT_STOCK", "Insufficient stock")
        order = Order(tenant_id=tenant, status="PENDING", total_amount=0)
        session.add(order)
        session.flush()
        total = 0
        for product in products:
            quantity = quantities[product.id]
            product.stock -= quantity
            line_amount = product.unit_price * quantity
            total += line_amount
            session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    unit_price=product.unit_price,
                    quantity=quantity,
                    line_amount=line_amount,
                )
            )
        order.total_amount = total
        session.add(
            Outbox(
                event_id=uuid.uuid4(),
                event_type="order.created",
                aggregate_id=order.id,
                payload=json.dumps({"order_id": str(order.id), "items": [{"sku": p.sku, "quantity": quantities[p.id]} for p in products]}),
            )
        )
        session.commit()
    except ApiError:
        session.rollback()
        raise
    session.expire_all()
    return load_order(session, tenant, order.id)


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Order:
    return load_order(session, tenant, order_id)


@app.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID,
    tenant: uuid.UUID = Depends(tenant_id),
    session: Session = Depends(get_session),
) -> Order:
    try:
        order = load_order(session, tenant, order_id, lock=True)
        if order.status != "PENDING":
            raise ApiError(409, "INVALID_ORDER_STATE", "Order cannot be canceled")
        product_ids = sorted((item.product_id for item in order.items), key=str)
        products = {
            product.id: product
            for product in session.scalars(
                select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update()
            )
        }
        for item in order.items:
            products[item.product_id].stock += item.quantity
        order.status = "CANCELED"
        session.add(
            Outbox(
                event_id=uuid.uuid4(),
                event_type="order.canceled",
                aggregate_id=order.id,
                payload=json.dumps({"order_id": str(order.id)}),
            )
        )
        session.commit()
    except ApiError:
        session.rollback()
        raise
    session.expire_all()
    return load_order(session, tenant, order.id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process one batch of events")
    args = parser.parse_args()
    if args.once:
        run_outbox_worker_once()
    else:
        print("Use --once to process outbox events")
