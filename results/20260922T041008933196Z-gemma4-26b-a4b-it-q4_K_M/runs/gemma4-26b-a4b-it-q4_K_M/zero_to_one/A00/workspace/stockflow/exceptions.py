from fastapi import HTTPException, status

class StockFlowException(HTTPException):
    def __init__(self, code: str, message: str, status_code: int, details: dict = None):
        super().__init__(
            status_code=status_code,
            detail={"error": {"code": code, "message": message, "details": details or {}}}
        )

class InvalidTenantException(StockFlowException):
    def __init__(self):
        super().__init__(code="INVALID_TENANT", message="Invalid tenant ID", status_code=status.HTTP_400_BAD_REQUEST)

class NotFoundException(StockFlowException):
    def __init__(self):
        super().__init__(code="NOT_FOUND", message="Resource not found", status_code=status.HTTP_404_NOT_FOUND)

class SkuAlreadyExistsException(StockFlowException):
    def __init__(self):
        super().__init__(code="SKU_ALREADY_EXISTS", message="SKU already exists for this tenant", status_code=status.HTTP_409_CONFLICT)

class InsufficientStockException(StockFlowException):
    def __init__(self):
        super().__init__(code="INSUFFICIENT_STOCK", message="Insufficient stock", status_code=status.HTTP_409_CONFLICT)

class InvalidOrderStateException(StockFlowException):
    def __init__(self):
        super().__init__(code="INVALID_ORDER_STATE", message="Invalid order state", status_code=status.HTTP_409_CONFLICT)
