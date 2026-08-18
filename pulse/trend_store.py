"""The longitudinal trend store: append-only, per-company, never edited in place.

This is the episodic memory of the whole system (see MEMORY.md). Every entry records the
cycle, the classification, and — critically — the exact agent_version and model that
PRODUCED that entry, never re-derived from a live registry lookup later. That's what makes
model-boundary detection possible: the record of "what produced this" travels with the data,
not with whatever happens to be active now.

Idempotency choice: append_trend_entry NO-OPS (logs, returns the existing entry) on a
duplicate (company_id, cycle) key rather than raising. A monitoring system must not let a
benign retry crash a sprint cycle — a raised exception would force every caller to
special-case it. The audit log still records the duplicate attempt, so the no-op is not
silent at the system level, only non-fatal to the caller.

Why idempotency matters more here than in a typical CRUD app: a duplicated trend entry would
corrupt the longitudinal record this whole project exists to protect, and could silently skew
the systemic-flag-spike detection in risk_scoring.py by counting one real flagged event as
two — inflating a single company's issue into what looks like a portfolio-wide spike.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pulse.paths import TREND_STORE_DIR, ensure_data_dirs

logger = logging.getLogger("pulse.trend_store")

REQUIRED_FIELDS = (
    "company_id",
    "cycle",
    "monitoring_track",
    "classifying_agent",  # which of the 6 agents' version/model gate the classification —
                          # change-impact-synthesizer for CHARTER (it's the causal-attribution
                          # gate on goal-drift-tracker's raw read), slo-risk-tracker for SLO
                          # (the classification is deterministic error-budget math, not
                          # narrative)
    "agent_version",
    "model",
    "metric_snapshot",
    "classification",
    "rationale",
)
# Optional field: "contributing_assessments" — a list of every agent's raw structured
# output that fed this entry (not just the classifying one), e.g. goal-drift-tracker's raw
# charter read alongside change-impact-synthesizer's attributable/noise verdict. Not required
# because SLO entries may have only one contributing agent, but populated whenever more than
# one agent's judgment fed the final call — this is what makes "why did we call this
# on_charter in S06" answerable from the record itself, not just from the classifying agent's
# own output.


class TrendStoreError(ValueError):
    pass


def _path_for(company_id: str) -> "Path":
    ensure_data_dirs()
    return TREND_STORE_DIR / f"{company_id}.jsonl"


def _read_all(company_id: str) -> list[dict[str, Any]]:
    path = _path_for(company_id)
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _cycle_sort_key(cycle: str) -> tuple[int, int]:
    year_str, s_str = cycle.split("-S")
    return (int(year_str), int(s_str))


def append_trend_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Append one trend entry. Idempotent, keyed by (company_id, cycle).

    Returns the entry that ends up on record for that key — either the one just written, or
    the pre-existing one if this was a duplicate call.
    """
    missing = [f for f in REQUIRED_FIELDS if f not in entry]
    if missing:
        raise TrendStoreError(f"trend entry missing required fields: {missing}")

    company_id = entry["company_id"]
    cycle = entry["cycle"]
    existing = _read_all(company_id)
    for prior in existing:
        if prior["cycle"] == cycle:
            logger.info(
                "append_trend_entry: duplicate entry for (%s, %s) — no-op, existing entry kept",
                company_id,
                cycle,
            )
            return prior

    entry = dict(entry)
    entry.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())

    path = _path_for(company_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def get_trend_history(company_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Return this company's trend entries, oldest-first. `limit` returns only the most
    recent `limit` entries (the bounded-recent-window retrieval scope agents are meant to
    use) — full history requires an explicit limit=None."""
    entries = sorted(_read_all(company_id), key=lambda e: _cycle_sort_key(e["cycle"]))
    if limit is not None:
        entries = entries[-limit:]
    return entries


def list_companies_with_history() -> list[str]:
    ensure_data_dirs()
    return sorted(p.stem for p in TREND_STORE_DIR.glob("*.jsonl"))
