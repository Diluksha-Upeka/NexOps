"""ShopAPI HTTP routers.

Exposes the simulated commerce endpoints: product listing, product
detail, order creation, and order detail.  Route handlers are thin —
they delegate to ShopService and translate domain errors into HTTP
responses.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.shopapi.schemas import (
    CreateOrderRequest,
    OrderResponse,
    ProductListResponse,
    ProductResponse,
)
from app.shopapi.service import (
    FaultInjectedError,
    InsufficientStockError,
    ProductNotFoundError,
    ShopService,
)

router = APIRouter(prefix="/shopapi", tags=["shopapi"])


@router.get("/health")
async def shopapi_health() -> dict[str, str]:
    """ShopAPI-specific health check."""
    return {"status": "ok", "service": "shopapi", "simulated": "true"}


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    session: AsyncSession = Depends(get_session),
) -> ProductListResponse:
    """List all products in the simulated store."""
    try:
        svc = ShopService(session)
        products, total = await svc.list_products()
        return ProductListResponse(
            items=[ProductResponse.model_validate(p) for p in products],
            total=total,
        )
    except FaultInjectedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    """Get a single product by ID."""
    try:
        svc = ShopService(session)
        product = await svc.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return ProductResponse.model_validate(product)
    except FaultInjectedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    body: CreateOrderRequest,
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    """Create a new order. Idempotent on idempotency_key."""
    try:
        svc = ShopService(session)
        order = await svc.create_order(body)
        return OrderResponse.model_validate(order)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FaultInjectedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    """Get a single order by ID."""
    svc = ShopService(session)
    order = await svc.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse.model_validate(order)
