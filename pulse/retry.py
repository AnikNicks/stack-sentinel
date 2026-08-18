"""Retry policy for MCP tool calls. Transient failures (timeout, rate-limit) retry with
exponential backoff up to a fixed max attempt count; permanent failures (schema mismatch,
not-found) never retry — they fail immediately and are incident-worthy.

Budget/runaway-loop cap: MAX_MCP_CALLS_PER_COMPANY_PER_CYCLE bounds how many MCP calls a
single company's cycle may make; the orchestrator enforces this and fails the cycle loudly
rather than retrying indefinitely if it's exceeded.
"""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 0.01  # kept tiny so real backoff still executes without
                                    # slowing down an 8-quarter simulation to a crawl
MAX_MCP_CALLS_PER_COMPANY_PER_CYCLE = 12


class TransientError(RuntimeError):
    """Retryable: timeouts, rate limits, connection resets."""


class PermanentError(RuntimeError):
    """Never retried: schema mismatch, company not found, malformed request."""


class BudgetExceededError(RuntimeError):
    """Raised when a cycle would exceed MAX_MCP_CALLS_PER_COMPANY_PER_CYCLE. The cycle fails
    loudly; it is never silently truncated or retried."""


def call_with_retry(
    fn: Callable[..., T], *args: Any,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs: Any,
) -> T:
    """Call fn(*args, **kwargs). Retries on TransientError with exponential backoff
    (base_delay * 2**attempt), up to max_attempts total tries. PermanentError propagates
    immediately on first occurrence, no retry."""
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except PermanentError:
            raise
        except TransientError as exc:
            last_error = exc
            if on_retry is not None:
                on_retry(attempt, exc)
            if attempt < max_attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
    assert last_error is not None
    raise last_error


class CallBudget:
    """Per-company-per-cycle MCP call budget. One instance per company per quarterly cycle."""

    def __init__(self, max_calls: int = MAX_MCP_CALLS_PER_COMPANY_PER_CYCLE):
        self.max_calls = max_calls
        self.calls_made = 0

    def consume(self, tool_name: str) -> None:
        self.calls_made += 1
        if self.calls_made > self.max_calls:
            raise BudgetExceededError(
                f"MCP call budget exceeded ({self.calls_made} > {self.max_calls}) on call "
                f"to '{tool_name}' — cycle fails loudly, not silently truncated."
            )
