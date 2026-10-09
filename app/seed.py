"""Seed script — populates the database with initial ShopAPI data.

Run with: ``uv run python -m app.seed``

Idempotent: checks whether products already exist before inserting.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from decimal import Decimal

# Windows: psycopg requires SelectorEventLoop, not ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.db.base import Base  # noqa: F401 — ensures models register
from app.shopapi.models import Product
from app.shopapi.telemetry_models import TelemetryEvent  # noqa: F401

# Deterministic UUIDs so tests and docs can reference them
PRODUCT_DATA = [
    {
        "id": uuid.UUID("a1b2c3d4-0001-4000-8000-000000000001"),
        "name": "Wireless Headphones Pro",
        "description": "Premium noise-cancelling wireless headphones with 30-hour battery life.",
        "price": Decimal("149.99"),
        "stock": 50,
        "category": "electronics",
    },
    {
        "id": uuid.UUID("a1b2c3d4-0001-4000-8000-000000000002"),
        "name": "Ergonomic Keyboard",
        "description": "Split mechanical keyboard with programmable keys and USB-C.",
        "price": Decimal("89.99"),
        "stock": 120,
        "category": "electronics",
    },
    {
        "id": uuid.UUID("a1b2c3d4-0001-4000-8000-000000000003"),
        "name": "Organic Coffee Beans (1kg)",
        "description": "Single-origin Colombian Arabica beans, medium roast.",
        "price": Decimal("24.50"),
        "stock": 200,
        "category": "food",
    },
    {
        "id": uuid.UUID("a1b2c3d4-0001-4000-8000-000000000004"),
        "name": "Running Shoes X1",
        "description": "Lightweight trail running shoes with responsive cushioning.",
        "price": Decimal("129.00"),
        "stock": 75,
        "category": "sports",
    },
    {
        "id": uuid.UUID("a1b2c3d4-0001-4000-8000-000000000005"),
        "name": "Desk Lamp LED",
        "description": "Adjustable LED desk lamp with colour temperature control.",
        "price": Decimal("45.00"),
        "stock": 90,
        "category": "home",
    },
    {
        "id": uuid.UUID("a1b2c3d4-0001-4000-8000-000000000006"),
        "name": "Stainless Steel Water Bottle",
        "description": "750ml insulated bottle — keeps drinks cold 24h, hot 12h.",
        "price": Decimal("19.99"),
        "stock": 300,
        "category": "home",
    },
]


async def seed_products(session: AsyncSession) -> int:
    """Insert seed products if the table is empty. Returns count inserted."""
    count_result = await session.execute(select(func.count(Product.id)))
    existing = count_result.scalar_one()
    if existing > 0:
        print(f"  ⏭  Products table already has {existing} rows — skipping seed.")
        return 0

    for data in PRODUCT_DATA:
        session.add(Product(**data))
    await session.commit()
    print(f"  ✅ Seeded {len(PRODUCT_DATA)} products.")
    return len(PRODUCT_DATA)


async def main() -> None:
    settings = get_settings()
    print(f"🌱 Seeding database: {settings.database_url.split('@')[-1]}")

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        await seed_products(session)

    await engine.dispose()
    print("🌱 Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
