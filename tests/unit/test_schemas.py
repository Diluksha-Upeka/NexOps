"""Unit tests for ShopAPI schemas."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.shopapi.schemas import (
    CreateOrderRequest,
    OrderItemRequest,
    ProductResponse,
)


class TestProductResponse:
    """Verify product response schema."""

    def test_from_dict(self) -> None:
        data = {
            "id": uuid4(),
            "name": "Test Widget",
            "description": "A fine widget",
            "price": Decimal("9.99"),
            "stock": 10,
            "category": "widgets",
            "created_at": "2026-01-01T00:00:00Z",
        }
        resp = ProductResponse(**data)
        assert resp.name == "Test Widget"
        assert resp.price == Decimal("9.99")


class TestCreateOrderRequest:
    """Verify order creation request validation."""

    def test_valid_order(self) -> None:
        req = CreateOrderRequest(
            idempotency_key="order-001",
            customer_email="alice@example.com",
            items=[
                OrderItemRequest(product_id=uuid4(), quantity=2),
            ],
        )
        assert len(req.items) == 1

    def test_empty_items_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateOrderRequest(
                idempotency_key="order-002",
                customer_email="bob@example.com",
                items=[],
            )

    def test_quantity_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OrderItemRequest(product_id=uuid4(), quantity=0)

    def test_quantity_over_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OrderItemRequest(product_id=uuid4(), quantity=101)

    def test_empty_idempotency_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateOrderRequest(
                idempotency_key="",
                customer_email="test@example.com",
                items=[OrderItemRequest(product_id=uuid4(), quantity=1)],
            )
