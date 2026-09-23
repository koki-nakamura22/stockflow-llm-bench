"""Product router for StockFlow Mini."""
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import SessionLocal
from .models import Product
from .schemas import ProductCreate, ProductOut
from .dependencies import get_tenant_id

router = APIRouter(prefix="/products", tags=["products"])

# Dependency to get DB session
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    product = Product(
        tenant_id=tenant_id,
        sku=payload.sku,
        name=payload.name,
        unit_price=payload.unit_price,
        stock=payload.stock,
    )
    db.add(product)
    try:
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "SKU_ALREADY_EXISTS", "message": "SKU already exists", "details": {}}},
        )
    return product

@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: Session = Depends(get_db),
):
    stmt = select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    result = db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Product not found", "details": {}}},
        )
    return product
