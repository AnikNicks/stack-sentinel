"""Read-only rollups over the trend store, incident log, and audit log — a population-level
view of how the six classifiers are performing over many cycles, not just per-incident.
Incident-shaped observability (something flagged, something didn't) already exists; this adds
the view of classifier stability, tool-call efficiency headroom, incident rate, and
human-approval turnaround alongside it. No new write path, no new judgment call — every
number here is a pure aggregation of data other modules already produce. Surfaced on the
dashboard's system-health panel (dashboard/api's GET /metrics).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pulse import incidents as incidents_module
from pulse import policy_rules
from pulse.audit_log import read_log
from pulse.trend_store import get_trend_history, list_companies_with_history


def classification_consistency(agent: str, company_id: str) -> dict[str, Any]:
    """Across this company's full trend history, what fraction of consecutive cycles kept
    the same classification, for entries classified by `agent`? A crude stability proxy: a
    classifier that flips its verdict cycle-to-cycle without any real triggering event is a
    candidate for review, even if no single flip looked wrong in isolation."""
    entries = [e for e in get_trend_history(company_id) if e.get("classifying_agent") == agent]
    if len(entries) < 2:
        return {"agent": agent, "company_id": company_id, "cycles_compared": 0,
                "consistent_transitions": 0, "consistency_pct": None}
    consistent = sum(
        1 for prev, curr in zip(entries, entries[1:])
        if prev["classification"] == curr["classification"]
    )
    total = len(entries) - 1
    return {
        "agent": agent, "company_id": company_id, "cycles_compared": total,
        "consistent_transitions": consistent,
        "consistency_pct": round(100 * consistent / total, 1),
    }


def tool_call_efficiency(agent: str, call_cap: int) -> dict[str, Any]:
    """Mean MCP tool calls per invocation for `agent`, against its own stated hard cap (the
    "Total tool calls this invocation" limit from its .claude/agents/<agent>.md — that cap
    lives in the prompt file, not in code, so the caller passes it in). Invocations are
    approximated by grouping audit_log entries for this agent into runs where consecutive
    calls are within 5 seconds of each other — this repo doesn't tag calls with an
    invocation id, so this is good enough for headroom reporting, not precise per-call
    attribution."""
    calls = [e for e in read_log() if e["agent"] == agent]
    if not calls:
        return {"agent": agent, "call_cap": call_cap, "invocations": 0,
                "mean_calls_per_invocation": None, "headroom_pct": None}
    groups: list[list[dict[str, Any]]] = []
    for call in calls:
        ts = datetime.fromisoformat(call["timestamp"])
        if groups and (ts - datetime.fromisoformat(groups[-1][-1]["timestamp"])).total_seconds() <= 5:
            groups[-1].append(call)
        else:
            groups.append([call])
    mean_calls = sum(len(g) for g in groups) / len(groups)
    return {
        "agent": agent, "call_cap": call_cap, "invocations": len(groups),
        "mean_calls_per_invocation": round(mean_calls, 2),
        "headroom_pct": round(100 * (1 - mean_calls / call_cap), 1) if call_cap else None,
    }


def incident_rate_by_kind_and_tier() -> dict[str, dict[str, int]]:
    """Count all recorded incidents, grouped by kind and by risk_tier."""
    by_kind: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for bundle in incidents_module.list_incidents():
        by_kind[bundle["kind"]] = by_kind.get(bundle["kind"], 0) + 1
        by_tier[bundle["risk_tier"]] = by_tier.get(bundle["risk_tier"], 0) + 1
    return {"by_kind": by_kind, "by_risk_tier": by_tier}


def approval_turnaround() -> list[dict[str, Any]]:
    """For every incident that reached pending_human_approval and has since been
    approved/rejected, business days between detected_at and reviewed_at, checked against
    the same SLA machinery policy_rules.py already uses for review timeliness.

    Known limitation in this simulated environment: detected_at is the SIMULATED cycle date
    (see pulse/incidents.create_incident), while reviewed_at is a real wall-clock timestamp
    (pulse/incidents.record_approval_decision uses datetime.now()). In
    scripts/simulate_production_run.py's scripted run these two clocks aren't aligned, so the
    printed business-day figures for that run are not meaningful — the SLA math itself is
    correct; only the demo's two input timestamps are on different clocks. In a real
    deployment both timestamps are real wall-clock time and this figure is meaningful as-is.
    """
    results = []
    for bundle in incidents_module.list_incidents():
        if bundle["status"] not in ("approved", "rejected") or not bundle.get("reviewed_at"):
            continue
        detected = date.fromisoformat(bundle["detected_at"])
        reviewed = date.fromisoformat(bundle["reviewed_at"][:10])
        elapsed = policy_rules.business_days_between(detected, reviewed)
        results.append({
            "incident_id": bundle["incident_id"],
            "status": bundle["status"],
            "business_days_elapsed": elapsed,
            "within_sla": elapsed <= policy_rules.ENGINEERING_REVIEW_SLA_BUSINESS_DAYS,
        })
    return results


def system_health_summary() -> dict[str, Any]:
    """One rollup combining all of the above, for the dashboard's system-health panel."""
    return {
        "incident_rates": incident_rate_by_kind_and_tier(),
        "approval_turnaround": approval_turnaround(),
        "companies_tracked": list_companies_with_history(),
    }
