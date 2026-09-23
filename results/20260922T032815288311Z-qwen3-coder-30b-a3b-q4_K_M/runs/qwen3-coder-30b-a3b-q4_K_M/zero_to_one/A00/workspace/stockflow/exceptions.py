from fastapi import HTTPException, status

class StockFlowException(Exception):
    def __init__(self, code: str, message: str, details: dict = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

class InvalidTenantException(StockFlowException):
    def __init__(self):
        super().__init__("INVALID_TENANT", "Invalid tenant ID")

class ProductNotFoundException(StockFlowException):
    def __init__(self):
        super().__init__("NOT_FOUND", "Product not found")

class OrderNotFoundException(StockFlowException):
    def __init__(self):
        super().__init__("NOT_FOUND", "Order not found")

class SKUAlreadyExistsException(StockFlowException):
    def __init__(self):
        super().__init__("SKU_ALREADY_EXISTS", "SKU already exists")

class InsufficientStockException(StockFlowException):
    def __init__(self):
        super().__init__("INSUFFICIENT_STOCK", "Insufficient stock")

class InvalidOrderStateException(StockFlowException):
    def __init__(self):
        super().__init__("INVALID_ORDER_STATE", "Invalid order state")