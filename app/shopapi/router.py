"""ShopAPI HTTP routers.

Exposes the simulated commerce endpoints: product listing, product
detail, order creation, and order detail.  Route handlers are thin —
they delegate to ShopService and translate domain errors into HTTP
responses.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.shopapi.models import Order, Product
from app.shopapi.schemas import (
    CreateOrderRequest,
    OrderListResponse,
    OrderResponse,
    OrderUpdateRequest,
    ProductCreateRequest,
    ProductListResponse,
    ProductResponse,
    ProductUpdateRequest,
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


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    body: ProductCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    product = Product(**body.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return ProductResponse.model_validate(product)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await session.commit()
    await session.refresh(product)
    return ProductResponse.model_validate(product)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(
    product_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        await session.delete(product)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Product is used by an order") from exc


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


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(session: AsyncSession = Depends(get_session)) -> OrderListResponse:
    result = await session.execute(select(Order).order_by(Order.created_at.desc()))
    orders = list(result.scalars().unique().all())
    total = (await session.execute(select(func.count(Order.id)))).scalar_one()
    return OrderListResponse(
        items=[OrderResponse.model_validate(order) for order in orders], total=total
    )


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


@router.patch("/orders/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: uuid.UUID,
    body: OrderUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = body.status
    await session.commit()
    await session.refresh(order)
    return OrderResponse.model_validate(order)


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    await session.delete(order)
    await session.commit()
