"""Idempotency tests."""

import os
import uuid

import requests

BASE_URL = os.environ.get("BASE_URL", "http://app:8000")


def test_idempotency_basic() -> None:
    """Test basic idempotency functionality."""
    tenant = str(uuid.uuid4())
    headers = {"X-Tenant-Id": tenant}
    
    # Create a product
    product_response = requests.post(
        f"{BASE_URL}/products",
        headers=headers,
        json={"sku": "IDEMPOTENCY-1", "name": "Idempotency test product", "unit_price": 100, "stock": 10},
        timeout=10,
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["id"]
    
    # Create an order with idempotency key
    order_body = {"items": [{"product_id": product_id, "quantity": 2}]}
    response1 = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers, "Idempotency-Key": "test-key-1"},
        json=order_body,
        timeout=10,
    )
    assert response1.status_code == 201
    order1 = response1.json()
    
    # Create the same order with same idempotency key
    response2 = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers, "Idempotency-Key": "test-key-1"},
        json=order_body,
        timeout=10,
    )
    assert response2.status_code == 201
    order2 = response2.json()
    
    # Should return the same order
    assert order1["id"] == order2["id"]
    
    # Check that stock was only reduced once
    product_response = requests.get(f"{BASE_URL}/products/{product_id}", headers=headers, timeout=10)
    assert product_response.status_code == 200
    assert product_response.json()["stock"] == 8


def test_idempotency_conflict() -> None:
    """Test idempotency conflict detection."""
    tenant = str(uuid.uuid4())
    headers = {"X-Tenant-Id": tenant}
    
    # Create a product
    product_response = requests.post(
        f"{BASE_URL}/products",
        headers=headers,
        json={"sku": "IDEMPOTENCY-2", "name": "Idempotency test product 2", "unit_price": 100, "stock": 10},
        timeout=10,
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["id"]
    
    # Create an order with idempotency key
    order_body1 = {"items": [{"product_id": product_id, "quantity": 2}]}
    response1 = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers, "Idempotency-Key": "test-key-2"},
        json=order_body1,
        timeout=10,
    )
    assert response1.status_code == 201
    
    # Create the same key with different request (should fail)
    order_body2 = {"items": [{"product_id": product_id, "quantity": 3}]}
    response2 = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers, "Idempotency-Key": "test-key-2"},
        json=order_body2,
        timeout=10,
    )
    assert response2.status_code == 409
    assert response2.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_idempotency_different_tenants() -> None:
    """Test that same idempotency key works across different tenants."""
    tenant1 = str(uuid.uuid4())
    tenant2 = str(uuid.uuid4())
    headers1 = {"X-Tenant-Id": tenant1}
    headers2 = {"X-Tenant-Id": tenant2}
    
    # Create products
    product_response1 = requests.post(
        f"{BASE_URL}/products",
        headers=headers1,
        json={"sku": "IDEMPOTENCY-3", "name": "Idempotency test product 3", "unit_price": 100, "stock": 10},
        timeout=10,
    )
    assert product_response1.status_code == 201
    product_id1 = product_response1.json()["id"]
    
    product_response2 = requests.post(
        f"{BASE_URL}/products",
        headers=headers2,
        json={"sku": "IDEMPOTENCY-3", "name": "Idempotency test product 3", "unit_price": 100, "stock": 10},
        timeout=10,
    )
    assert product_response2.status_code == 201
    product_id2 = product_response2.json()["id"]
    
    # Create orders with same idempotency key but different tenants
    order_body = {"items": [{"product_id": product_id1, "quantity": 2}]}
    response1 = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers1, "Idempotency-Key": "same-key"},
        json=order_body,
        timeout=10,
    )
    assert response1.status_code == 201
    
    order_body = {"items": [{"product_id": product_id2, "quantity": 2}]}
    response2 = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers2, "Idempotency-Key": "same-key"},
        json=order_body,
        timeout=10,
    )
    assert response2.status_code == 201
    
    # Both should succeed (different tenants, so same key is allowed)
    # Check that both orders were created with different product ids
    assert response1.json()["items"][0]["product_id"] == product_id1
    assert response2.json()["items"][0]["product_id"] == product_id2


def test_idempotency_key_validation() -> None:
    """Test idempotency key validation."""
    tenant = str(uuid.uuid4())
    headers = {"X-Tenant-Id": tenant}
    
    # Create a product
    product_response = requests.post(
        f"{BASE_URL}/products",
        headers=headers,
        json={"sku": "IDEMPOTENCY-4", "name": "Idempotency test product 4", "unit_price": 100, "stock": 10},
        timeout=10,
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["id"]
    
    # Test with empty idempotency key (should fail)
    order_body = {"items": [{"product_id": product_id, "quantity": 2}]}
    response = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers, "Idempotency-Key": ""},
        json=order_body,
        timeout=10,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
    
    # Test with too long idempotency key (should fail)
    long_key = "a" * 129
    response = requests.post(
        f"{BASE_URL}/orders",
        headers={**headers, "Idempotency-Key": long_key},
        json=order_body,
        timeout=10,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"