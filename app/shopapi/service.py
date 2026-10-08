"""ShopAPI service layer — products and orders with fault injection.

Business logic lives here, not in route handlers.  Every database
operation is instrumented: structured logs are emitted, metric samples
and trace spans are recorded via the TelemetryRecorder, and active
faults (latency, errors, dependency timeouts) are applied transparently.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shopapi.models import Order, OrderItem, Product
from app.shopapi.schemas import CreateOrderRequest
from app.shopapi.simulator import (
    ScenarioKey,
    SimulatorState,
    get_simulator,
)
from app.shopapi.telemetry import TelemetryRecorder, generate_span_id, generate_trace_id

logger = logging.getLogger(__name__)


class ShopService:
    """Encapsulates ShopAPI business logic with fault injection."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._simulator: SimulatorState = get_simulator()

    # ── Product operations ────────────────────────────────────────────

    async def list_products(self) -> tuple[list[Product], int]:
        """Return all products with telemetry and fault injection."""
        trace_id = generate_trace_id()
        root_span_id = generate_span_id()
        start = time.monotonic()
        recorder = self._get_recorder()

        try:
            # Apply faults
            await self._apply_db_latency(trace_id, root_span_id)
            self._check_connection_exhaustion()
            self._check_elevated_errors(route="/shopapi/products")
            await self._apply_bad_release_delay(trace_id, root_span_id)

            # Actual query
            db_start = time.monotonic()
            result = await self._session.execute(select(Product).order_by(Product.name))
            products = list(result.scalars().all())
            db_duration_ms = (time.monotonic() - db_start) * 1000

            count_result = await self._session.execute(select(func.count(Product.id)))
            total = count_result.scalar_one()

            # Record DB span
            await recorder.record_span(
                name="db.query.products",
                duration_ms=db_duration_ms,
                trace_id=trace_id,
                span_id=generate_span_id(),
                parent_span_id=root_span_id,
            )

            duration_ms = (time.monotonic() - start) * 1000

            # Record request metric + log
            await recorder.record_request(
                route="/shopapi/products",
                method="GET",
                status_code=200,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
            )
            await recorder.record_log(
                level="INFO",
                message=f"Listed {len(products)} products",
                route="/shopapi/products",
                method="GET",
                status_code=200,
                trace_id=trace_id,
                extra_attributes={"product_count": len(products)},
            )
            await self._session.commit()

            return products, total

        except FaultInjectedError:
            duration_ms = (time.monotonic() - start) * 1000
            await recorder.record_request(
                route="/shopapi/products",
                method="GET",
                status_code=500,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
            )
            await recorder.record_log(
                level="ERROR",
                message="Request failed due to injected fault",
                route="/shopapi/products",
                method="GET",
                status_code=500,
                trace_id=trace_id,
            )
            await self._session.commit()
            raise

    async def get_product(self, product_id: uuid.UUID) -> Product | None:
        """Return a single product by ID."""
        trace_id = generate_trace_id()
        root_span_id = generate_span_id()
        start = time.monotonic()
        recorder = self._get_recorder()

        try:
            self._check_elevated_errors(route="/shopapi/products/{id}")

            result = await self._session.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
            duration_ms = (time.monotonic() - start) * 1000

            status = 200 if product else 404
            await recorder.record_request(
                route="/shopapi/products/{id}",
                method="GET",
                status_code=status,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
            )
            await recorder.record_log(
                level="INFO" if product else "WARNING",
                message=f"Product lookup {'found' if product else 'not found'}: {product_id}",
                route="/shopapi/products/{id}",
                method="GET",
                status_code=status,
                trace_id=trace_id,
            )
            await self._session.commit()
            return product

        except FaultInjectedError:
            duration_ms = (time.monotonic() - start) * 1000
            await recorder.record_request(
                route="/shopapi/products/{id}",
                method="GET",
                status_code=500,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
            )
            await self._session.commit()
            raise

    # ── Order operations ──────────────────────────────────────────────

    async def create_order(self, req: CreateOrderRequest) -> Order:
        """Create an order. Idempotent on idempotency_key."""
        trace_id = generate_trace_id()
        root_span_id = generate_span_id()
        start = time.monotonic()
        recorder = self._get_recorder()

        # Check idempotency — return existing order if key already used
        existing = await self._session.execute(
            select(Order).where(Order.idempotency_key == req.idempotency_key)
        )
        existing_order = existing.scalar_one_or_none()
        if existing_order is not None:
            duration_ms = (time.monotonic() - start) * 1000
            await recorder.record_request(
                route="/shopapi/orders",
                method="POST",
                status_code=200,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
                extra_attributes={"idempotent_hit": True},
            )
            await recorder.record_log(
                level="INFO",
                message=f"Idempotent order hit: {req.idempotency_key}",
                route="/shopapi/orders",
                method="POST",
                status_code=200,
                trace_id=trace_id,
            )
            await self._session.commit()
            return existing_order

        try:
            self._check_connection_exhaustion()
            self._check_elevated_errors(route="/shopapi/orders")

            # Simulate dependency call (payment/shipping)
            await self._call_dependency("payment-service", trace_id, root_span_id)

            # Validate products and calculate total
            total = Decimal("0.00")
            order_items: list[OrderItem] = []
            for item_req in req.items:
                prod_result = await self._session.execute(
                    select(Product).where(Product.id == item_req.product_id)
                )
                product = prod_result.scalar_one_or_none()
                if product is None:
                    raise ProductNotFoundError(f"Product {item_req.product_id} not found")
                if product.stock < item_req.quantity:
                    raise InsufficientStockError(
                        f"Insufficient stock for {product.name}: "
                        f"requested {item_req.quantity}, available {product.stock}"
                    )

                line_total = product.price * item_req.quantity
                total += line_total
                order_items.append(
                    OrderItem(
                        product_id=product.id,
                        quantity=item_req.quantity,
                        unit_price=product.price,
                    )
                )
                # Reduce stock
                product.stock -= item_req.quantity

            order = Order(
                idempotency_key=req.idempotency_key,
                customer_email=req.customer_email,
                total=total,
                status="confirmed",
                items=order_items,
            )
            self._session.add(order)
            await self._session.commit()
            await self._session.refresh(order)

            duration_ms = (time.monotonic() - start) * 1000
            await recorder.record_request(
                route="/shopapi/orders",
                method="POST",
                status_code=201,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
            )
            await recorder.record_log(
                level="INFO",
                message=f"Order created: {order.id} total=${total}",
                route="/shopapi/orders",
                method="POST",
                status_code=201,
                trace_id=trace_id,
                extra_attributes={
                    "order_id": str(order.id),
                    "total": str(total),
                    "item_count": len(order_items),
                },
            )
            await self._session.commit()
            return order

        except FaultInjectedError:
            await self._session.rollback()
            duration_ms = (time.monotonic() - start) * 1000
            await recorder.record_request(
                route="/shopapi/orders",
                method="POST",
                status_code=500,
                duration_ms=duration_ms,
                trace_id=trace_id,
                span_id=root_span_id,
            )
            await recorder.record_log(
                level="ERROR",
                message="Order creation failed due to injected fault",
                route="/shopapi/orders",
                method="POST",
                status_code=500,
                trace_id=trace_id,
            )
            await self._session.commit()
            raise

    async def get_order(self, order_id: uuid.UUID) -> Order | None:
        """Return a single order by ID with its items."""
        trace_id = generate_trace_id()
        start = time.monotonic()
        recorder = self._get_recorder()

        result = await self._session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        duration_ms = (time.monotonic() - start) * 1000
        status = 200 if order else 404

        await recorder.record_request(
            route="/shopapi/orders/{id}",
            method="GET",
            status_code=status,
            duration_ms=duration_ms,
            trace_id=trace_id,
        )
        await self._session.commit()
        return order

    # ── Fault injection helpers ───────────────────────────────────────

    async def _apply_db_latency(self, trace_id: str, parent_span_id: str) -> None:
        """Inject artificial database latency if the scenario is active."""
        delay_ms = self._simulator.get_fault_parameter(ScenarioKey.DB_LATENCY, "delay_ms")
        if delay_ms is None:
            return

        # Add jitter: ±10%
        jitter = delay_ms * 0.1
        actual_delay_ms = delay_ms + random.uniform(-jitter, jitter)
        await asyncio.sleep(actual_delay_ms / 1000.0)

        recorder = self._get_recorder()
        await recorder.record_span(
            name="db.query.injected_delay",
            duration_ms=actual_delay_ms,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            extra_attributes={
                "fault": "db_latency",
                "injected_delay_ms": round(actual_delay_ms, 1),
            },
        )

    async def _apply_bad_release_delay(self, trace_id: str, parent_span_id: str) -> None:
        """Inject latency from a 'bad release' scenario."""
        delay_ms = self._simulator.get_fault_parameter(ScenarioKey.BAD_RELEASE, "delay_ms")
        if delay_ms is None:
            return

        jitter = delay_ms * 0.1
        actual_delay_ms = delay_ms + random.uniform(-jitter, jitter)
        await asyncio.sleep(actual_delay_ms / 1000.0)

        recorder = self._get_recorder()
        await recorder.record_span(
            name="db.query.slow_after_release",
            duration_ms=actual_delay_ms,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            extra_attributes={"fault": "bad_release"},
        )

    def _check_connection_exhaustion(self) -> None:
        """Simulate connection pool exhaustion by failing deterministically."""
        failure_rate = self._simulator.get_fault_parameter(
            ScenarioKey.DB_CONN_EXHAUSTION, "failure_rate"
        )
        if failure_rate is None:
            return
        if random.random() < failure_rate:
            raise FaultInjectedError(
                "Connection pool exhausted — unable to acquire database connection"
            )

    def _check_elevated_errors(self, route: str) -> None:
        """Simulate elevated 5xx errors by failing deterministically."""
        error_rate = self._simulator.get_fault_parameter(ScenarioKey.ELEVATED_5XX, "error_rate")
        if error_rate is None:
            return
        if random.random() < error_rate:
            raise FaultInjectedError(f"Internal server error on {route}")

    async def _call_dependency(self, dep_name: str, trace_id: str, parent_span_id: str) -> None:
        """Simulate a dependency call. May timeout if fault is active."""
        recorder = self._get_recorder()
        dep_span_id = generate_span_id()

        timeout_ms = self._simulator.get_fault_parameter(
            ScenarioKey.DEPENDENCY_TIMEOUT, "timeout_ms"
        )

        if timeout_ms is not None:
            # Simulate the slow dependency
            actual_timeout = timeout_ms + random.uniform(-200, 200)
            await asyncio.sleep(actual_timeout / 1000.0)
            await recorder.record_span(
                name=f"http.client.{dep_name}",
                duration_ms=actual_timeout,
                trace_id=trace_id,
                span_id=dep_span_id,
                parent_span_id=parent_span_id,
                error=True,
                extra_attributes={
                    "dependency": dep_name,
                    "fault": "dependency_timeout",
                    "timeout": True,
                },
            )
            await recorder.record_log(
                level="ERROR",
                message=f"Dependency {dep_name} timed out after {actual_timeout:.0f}ms",
                trace_id=trace_id,
                extra_attributes={"dependency": dep_name},
            )
            raise FaultInjectedError(f"Dependency {dep_name} timed out")
        else:
            # Normal fast dependency call
            normal_duration = random.uniform(5, 30)
            await recorder.record_span(
                name=f"http.client.{dep_name}",
                duration_ms=normal_duration,
                trace_id=trace_id,
                span_id=dep_span_id,
                parent_span_id=parent_span_id,
            )

    def _get_recorder(self) -> TelemetryRecorder:
        """Build a recorder tagged with the currently active scenario."""
        # Find the first active scenario key for tagging
        active = self._simulator.active_faults
        scenario_id = next(iter(active), None)
        return TelemetryRecorder(
            self._session,
            scenario_id=scenario_id.value if scenario_id else None,
        )


# ── Domain errors ─────────────────────────────────────────────────────


class FaultInjectedError(Exception):
    """Raised when a fault scenario causes a simulated failure."""


class ProductNotFoundError(Exception):
    """Raised when a referenced product does not exist."""


class InsufficientStockError(Exception):
    """Raised when order quantity exceeds available stock."""
