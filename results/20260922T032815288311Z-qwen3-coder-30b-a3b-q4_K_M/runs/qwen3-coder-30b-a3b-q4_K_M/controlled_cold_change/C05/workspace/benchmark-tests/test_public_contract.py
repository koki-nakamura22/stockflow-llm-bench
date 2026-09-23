"""Visible smoke tests. The private evaluator contains the scored cases."""

import os
import uuid

import requests

BASE_URL = os.environ.get("BASE_URL", "http://app:8000")


def test_health() -> None:
    response = requests.get(f"{BASE_URL}/health", timeout=10)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_product_round_trip() -> None:
    tenant = str(uuid.uuid4())
    headers = {"X-Tenant-Id": tenant}
    created = requests.post(
        f"{BASE_URL}/products",
        headers=headers,
        json={"sku": "PUBLIC-1", "name": "Public product", "unit_price": 120, "stock": 4},
        timeout=10,
    )
    assert created.status_code == 201, created.text
    fetched = requests.get(f"{BASE_URL}/products/{created.json()['id']}", headers=headers, timeout=10)
    assert fetched.status_code == 200
    assert fetched.json()["sku"] == "PUBLIC-1"

