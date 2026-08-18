"""Deterministic, literal/countable policy checks — run ALONGSIDE vector-retrieved clause
text (pulse/vector_store.py + the policy-compliance-checker agent), never instead of it.

This is the deterministic/agentic split applied to policy: retrieval and counting are code;
interpreting whether a borderline case is "close enough" to a clause's intent is the one
place the agent's judgment earns its place. Embeddings are bad at precision requirements — a
policy trigger like "two or more consecutive periods" must be counted exactly, never
approximated by similarity search. That's why this module exists as plain Python instead of
being folded into the vector search.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

CONSECUTIVE_WARNING_THRESHOLD_FOR_CREDIT_COMMITTEE = 2
DEAL_PARTNER_REVIEW_SLA_BUSINESS_DAYS = 5
STALE_PENDING_REVIEW_BUSINESS_DAYS = 10


def _quarter_sort_key(quarter: str) -> tuple[int, int]:
    year_str, q_str = quarter.split("-Q")
    return (int(year_str), int(q_str))


def count_consecutive_warning_quarters(trend_entries: list[dict[str, Any]],
                                        warning_value: str = "warning") -> int:
    """Count the current unbroken streak of `classification == warning_value` entries,
    counting backward from the most recent quarter. Entries must be oldest-first."""
    entries = sorted(trend_entries, key=lambda e: _quarter_sort_key(e["quarter"]))
    count = 0
    for entry in reversed(entries):
        if entry.get("classification") == warning_value:
            count += 1
        else:
            break
    return count


def credit_committee_clause_triggered(trend_entries: list[dict[str, Any]]) -> bool:
    """'Any covenant classified as warning for two or more consecutive reporting periods
    must be reported to the Credit Committee at the next scheduled meeting, regardless of
    trend direction.' — literal N-quarters count, exact per the policy text."""
    return count_consecutive_warning_quarters(trend_entries) >= CONSECUTIVE_WARNING_THRESHOLD_FOR_CREDIT_COMMITTEE


def business_days_between(start: date, end: date) -> int:
    """Count business days (Mon-Fri) strictly after `start` up to and including `end`.
    business_days_between(d, d) == 0."""
    if end <= start:
        return 0
    days = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            days += 1
        current += timedelta(days=1)
    return days


def deal_partner_review_sla_status(classified_at: date, as_of: date) -> dict[str, Any]:
    """'A portfolio company classified off_thesis must receive deal-partner review within 5
    business days of classification.' Returns whether the SLA is still open, and how many
    business days have elapsed."""
    elapsed = business_days_between(classified_at, as_of)
    return {
        "business_days_elapsed": elapsed,
        "sla_business_days": DEAL_PARTNER_REVIEW_SLA_BUSINESS_DAYS,
        "sla_breached": elapsed > DEAL_PARTNER_REVIEW_SLA_BUSINESS_DAYS,
    }


def is_pending_review_stale(detected_at: date, as_of: date,
                             threshold_business_days: int = STALE_PENDING_REVIEW_BUSINESS_DAYS) -> bool:
    """A pending_review incident that's sat unresolved past the threshold auto-escalates
    rather than being treated as implicit approval by silence (see incidents.py)."""
    return business_days_between(detected_at, as_of) > threshold_business_days
