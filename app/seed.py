"""Seed script — populates database with initial ShopAPI data, baseline telemetry,
and sample reproducible incidents.

Run with:
    ``uv run python -m app.seed``          # Standard idempotent seeding
    ``uv run python -m app.seed --demo``   # Seed active demo incident
    ``uv run python -m app.seed --reset``  # Destructive reset and reseed local dev data
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# Windows: psycopg requires SelectorEventLoop, not ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.db.base import Base  # noqa: F401 — ensures models register
from app.incidents.models import Incident
from app.shopapi.models import Product
from app.shopapi.telemetry_models import TelemetryEvent

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

DEMO_INCIDENTS = [
    {
        "id": uuid.UUID("c1d2e3f4-0001-4000-8000-000000000001"),
        "title": "ShopAPI latency spike on /products catalog endpoint",
        "description": "Customer requests to /products experiencing p95 response times over 1.4s.",
        "service": "shopapi",
        "severity": "high",
        "status": "open",
        "source": "simulator",
        "scenario_key": "db_latency",
    },
    {
        "id": uuid.UUID("c1d2e3f4-0001-4000-8000-000000000002"),
        "title": "ShopAPI database connection pool exhaustion",
        "description": "Intermittent HTTP 503 errors and connection timeouts during peak traffic.",
        "service": "shopapi",
        "severity": "critical",
        "status": "open",
        "source": "simulator",
        "scenario_key": "db_connection_exhaustion",
    },
    {
        "id": uuid.UUID("c1d2e3f4-0001-4000-8000-000000000003"),
        "title": "ShopAPI bad release query degradation",
        "description": "Slow response times following deployment of release v1.4.2.",
        "service": "shopapi",
        "severity": "medium",
        "status": "resolved",
        "source": "simulator",
        "scenario_key": "bad_release",
    },
]


async def seed_products(session: AsyncSession) -> int:
    """Insert seed products if the table is empty. Returns count inserted."""
    count_result = await session.execute(select(func.count(Product.id)))
    existing = count_result.scalar_one()
    if existing > 0:
        print(f"  [SKIP] Products table already has {existing} rows — skipping seed.")
        return 0

    for data in PRODUCT_DATA:
        session.add(Product(**data))
    await session.commit()
    print(f"  [OK] Seeded {len(PRODUCT_DATA)} products.")
    return len(PRODUCT_DATA)


async def seed_incidents(session: AsyncSession) -> int:
    """Insert seed incidents if the table is empty. Returns count inserted."""
    count_result = await session.execute(select(func.count(Incident.id)))
    existing = count_result.scalar_one()
    if existing > 0:
        print(f"  [SKIP] Incidents table already has {existing} rows — skipping seed.")
        return 0

    now = datetime.now(UTC)
    for inc_data in DEMO_INCIDENTS:
        inc = Incident(
            id=inc_data["id"],
            title=inc_data["title"],
            description=inc_data["description"],
            service=inc_data["service"],
            severity=inc_data["severity"],
            status=inc_data["status"],
            source=inc_data["source"],
            scenario_key=inc_data["scenario_key"],
            started_at=now - timedelta(minutes=30),
            created_at=now - timedelta(minutes=30),
            resolved_at=now - timedelta(minutes=10) if inc_data["status"] == "resolved" else None,
            version=1,
        )
        session.add(inc)

    await session.commit()
    print(f"  [OK] Seeded {len(DEMO_INCIDENTS)} initial demo incidents.")
    return len(DEMO_INCIDENTS)


async def seed_baseline_telemetry(session: AsyncSession) -> int:
    """Insert baseline telemetry events if table is empty. Returns count inserted."""
    count_result = await session.execute(select(func.count(TelemetryEvent.id)))
    existing = count_result.scalar_one()
    if existing > 0:
        print(f"  [SKIP] Telemetry events table already has {existing} rows — skipping seed.")
        return 0

    now = datetime.now(UTC)
    events: list[TelemetryEvent] = []

    # Generate normal baseline metrics over the past 30 minutes
    endpoints = [
        ("GET", "/shopapi/products", 200, 45.0),
        ("GET", "/shopapi/products/{id}", 200, 25.0),
        ("GET", "/shopapi/health", 200, 5.0),
        ("POST", "/shopapi/orders", 201, 80.0),
    ]

    for i in range(40):
        t = now - timedelta(minutes=30 - int(i * 0.75))
        method, route, status, base_dur = endpoints[i % len(endpoints)]
        dur = base_dur + (i % 7) * 4.2
        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]

        # Metric event
        events.append(
            TelemetryEvent(
                id=uuid.uuid4(),
                scenario_id=None,
                kind="metric",
                timestamp=t,
                service="shopapi",
                route=route,
                method=method,
                status_code=status,
                duration_ms=dur,
                trace_id=trace_id,
                span_id=span_id,
                attributes={"status_class": "2xx", "route_template": route},
            )
        )

        # Log event
        events.append(
            TelemetryEvent(
                id=uuid.uuid4(),
                scenario_id=None,
                kind="log",
                timestamp=t,
                service="shopapi",
                route=route,
                method=method,
                status_code=status,
                level="INFO",
                message=f"{method} {route} handled successfully in {dur:.1f}ms",
                trace_id=trace_id,
            )
        )

        # Trace span event
        events.append(
            TelemetryEvent(
                id=uuid.uuid4(),
                scenario_id=None,
                kind="span",
                timestamp=t,
                service="shopapi",
                duration_ms=dur,
                status_code=status,
                trace_id=trace_id,
                span_id=span_id,
                attributes={"span_name": f"HTTP {method} {route}", "error": False},
            )
        )

    session.add_all(events)
    await session.commit()
    print(f"  [OK] Seeded {len(events)} baseline telemetry events.")
    return len(events)


async def reset_demo_data(session: AsyncSession) -> None:
    """Clear demo domain tables for a clean restart."""
    print("  [RESET] Resetting local demo data...")
    await session.execute(delete(TelemetryEvent))
    await session.execute(delete(Incident))
    await session.execute(delete(Product))
    await session.commit()
    print("  [OK] Reset complete.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed NexOps local development data")
    parser.add_argument("--reset", action="store_true", help="Clear and reseed local demo data")
    parser.add_argument("--demo", action="store_true", help="Ensure an active demo incident exists")
    args = parser.parse_args()

    settings = get_settings()
    print(f"[SEED] NexOps Seeder: connecting to {settings.database_url.split('@')[-1]}")

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        if args.reset:
            await reset_demo_data(session)

        await seed_products(session)
        await seed_baseline_telemetry(session)
        await seed_incidents(session)

    await engine.dispose()
    print("[SEED] Database seeding complete.")


if __name__ == "__main__":
    asyncio.run(main())
