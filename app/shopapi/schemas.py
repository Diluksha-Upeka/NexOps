"""Pydantic request/response schemas for the ShopAPI endpoints.

These schemas define the public API contract. Internal SQLAlchemy models
are never exposed directly — responses are serialised through these.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

# ── Products ──────────────────────────────────────────────────────────


class ProductResponse(BaseModel):
    """Public representation of a product."""

    id: UUID
    name: str
    description: str
    price: Decimal
    stock: int
    category: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    """Paginated list of products."""

    items: list[ProductResponse]
    total: int


# ── Orders ────────────────────────────────────────────────────────────


class OrderItemRequest(BaseModel):
    """A single line item in a create-order request."""

    product_id: UUID
    quantity: int = Field(ge=1, le=100)


class CreateOrderRequest(BaseModel):
    """Request body for POST /orders."""

    idempotency_key: str = Field(min_length=1, max_length=100)
    customer_email: str = Field(min_length=3, max_length=255)
    items: list[OrderItemRequest] = Field(min_length=1, max_length=20)


class OrderItemResponse(BaseModel):
    """A line item in the order response."""

    id: UUID
    product_id: UUID
    quantity: int
    unit_price: Decimal

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    """Public representation of an order."""

    id: UUID
    idempotency_key: str
    status: str
    total: Decimal
    customer_email: str
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
