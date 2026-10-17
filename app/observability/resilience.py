"""Resilience engineering: timeouts, transient retries, and provider fallback.

Invariants enforced:
1. Retries apply ONLY to read-only, transient I/O operations (network, timeout, connection blips).
2. Mutations and remediation actions are NEVER retried automatically.
3. Client validation errors (400, 404, 409, 422) and policy denials are NEVER retried.
4. Provider fallback activates gracefully on LLM failure, logging the event and recording metrics.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

import httpx

from app.observability.metrics import record_llm_invocation

logger = logging.getLogger(__name__)

# Transient exceptions safe for read-only retries
TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.NetworkError,
    TimeoutError,
    asyncio.TimeoutError,
    ConnectionResetError,
    ConnectionRefusedError,
)


class ResilientTimeoutError(TimeoutError):
    """Raised when an operation exceeds its configured deadline."""

    def __init__(self, operation: str, timeout_seconds: float) -> None:
        super().__init__(f"Operation '{operation}' timed out after {timeout_seconds:.1f}s")
        self.operation = operation
        self.timeout_seconds = timeout_seconds


async def with_timeout[T](
    coro: Awaitable[T],
    timeout_seconds: float,
    operation_name: str = "operation",
) -> T:
    """Execute a coroutine within an enforced timeout deadline."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except TimeoutError as exc:
        logger.warning(
            "Timeout exceeded for %s (limit: %.1fs)",
            operation_name,
            timeout_seconds,
            extra={"structured": {"operation": operation_name, "timeout_seconds": timeout_seconds}},
        )
        raise ResilientTimeoutError(operation_name, timeout_seconds) from exc


async def retry_transient_async[T](
    coro_fn: Callable[[], Awaitable[T]],
    *,
    operation_name: str = "read_operation",
    max_retries: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 0.5,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
) -> T:
    """Retry a transient read-only operation with exponential backoff and full jitter.

    MUTATION WARNING: Must NEVER be called on state-mutating actions.
    """
    attempt = 0
    while True:
        try:
            return await coro_fn()
        except retryable_exceptions as exc:
            attempt += 1
            if attempt > max_retries:
                logger.error(
                    "Exhausted %d retries for %s: %s",
                    max_retries,
                    operation_name,
                    exc,
                    extra={
                        "structured": {
                            "operation": operation_name,
                            "attempts": attempt,
                            "error": str(exc),
                        }
                    },
                )
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            if jitter:
                delay = random.uniform(0.0, delay)

            logger.warning(
                "Transient error in %s (attempt %d/%d), retrying in %.3fs: %s",
                operation_name,
                attempt,
                max_retries,
                delay,
                exc,
                extra={
                    "structured": {
                        "operation": operation_name,
                        "attempt": attempt,
                        "retry_delay_seconds": delay,
                        "error_type": exc.__class__.__name__,
                    }
                },
            )
            await asyncio.sleep(delay)


async def execute_with_provider_fallback[T](
    primary_call: Callable[[], Awaitable[T]],
    fallback_call: Callable[[], Awaitable[T]],
    *,
    operation_name: str,
    provider: str = "hosted",
    model: str = "unknown",
) -> T:
    """Execute an LLM call with safe fallback to deterministic rules on failure."""
    start = time.perf_counter()
    try:
        result = await primary_call()
        record_llm_invocation(
            provider=provider,
            model=model,
            status="success",
            duration_seconds=time.perf_counter() - start,
        )
        return result
    except Exception as exc:
        duration = time.perf_counter() - start
        logger.warning(
            "Primary LLM provider %s failed for %s (took %.2fs): %s. "
            "Activating deterministic fallback.",
            provider,
            operation_name,
            duration,
            exc,
            extra={
                "structured": {
                    "operation": operation_name,
                    "provider": provider,
                    "model": model,
                    "error": str(exc),
                    "fallback": True,
                }
            },
        )
        record_llm_invocation(
            provider=provider,
            model=model,
            status="fallback",
            duration_seconds=duration,
        )
        return await fallback_call()
