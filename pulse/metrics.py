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

import json

from pulse import incidents as incidents_module
from pulse import policy_rules
from pulse.audit_log import read_log
from pulse.paths import LAYER_METRICS_DIR
from pulse.trend_store import get_trend_history, list_companies_with_history

# Each agent's own documented retrieval scope (its .claude/agents/<agent>.md `tools:`
# frontmatter) — the allowlist unexpected_tool_calls() checks real audit_log entries against.
# Sourced from the prompt files, not invented: a call outside this set is a real deviation
# from what that agent's own spec says it does.
#
# Note: pulse/orchestrator.py attributes the shared get_trend_history/append_trend_entry calls
# in each per-company cycle to that track's primary agent (goal-drift-tracker for CHARTER,
# slo-risk-tracker for SLO) — change-impact-synthesizer and model-boundary-interpreter receive
# that same fetched history pushed to them directly rather than calling a tool themselves, per
# their own retrieval-scope docs, so their real audit-log footprint is legitimately empty.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "goal-drift-tracker": {"get_system_charter", "get_system_metrics", "get_trend_history", "append_trend_entry"},
    "slo-risk-tracker": {"get_slo_agreement", "get_system_metrics", "get_trend_history", "append_trend_entry"},
    "change-impact-synthesizer": set(),
    "model-boundary-interpreter": set(),
    "portfolio-rollup-writer": {"list_portfolio_companies", "get_trend_history"},
    "policy-compliance-checker": {"search_policy", "search_company_policy"},
    "groundedness-checker": set(),
}


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


def schema_compliance_rate(company_id: str) -> dict[str, Any]:
    """Pure rollup, zero new data: what fraction of this company's recorded cycles ended in
    `assessment_failed` (a real schema-validation miss on the classifying agent's output) —
    tracking the RATE over time surfaces a slow-creeping regression well before it would show
    up as a single dramatic failure."""
    entries = get_trend_history(company_id)
    if not entries:
        return {"company_id": company_id, "total_cycles": 0, "assessment_failed_count": 0,
                "compliance_rate_pct": None}
    failed = sum(1 for e in entries if e.get("classification") == "assessment_failed")
    return {
        "company_id": company_id, "total_cycles": len(entries), "assessment_failed_count": failed,
        "compliance_rate_pct": round(100 * (1 - failed / len(entries)), 1),
    }


def unexpected_tool_calls(agent: str) -> list[dict[str, Any]]:
    """Pure rollup, zero new data: real audit_log entries for `agent` naming a tool outside
    its own documented allowlist (EXPECTED_TOOLS, sourced from its .claude/agents/*.md spec) —
    a real deviation from what that agent's own retrieval-scope section says it does."""
    expected = EXPECTED_TOOLS.get(agent, set())
    return [
        {"tool_name": e["tool_name"], "timestamp": e["timestamp"], "args": e["args"]}
        for e in read_log()
        if e["agent"] == agent and e["tool_name"] not in expected
    ]


def approval_quality_flags(min_review_minutes: float = 5.0) -> list[dict[str, Any]]:
    """Pure rollup, zero new data: for every decided incident, minutes elapsed between the
    incident's real wall-clock created_at and its real wall-clock reviewed_at (both are real
    datetime.now() timestamps in pulse/incidents.py — unlike approval_turnaround's detected_at,
    which is the simulated cycle date, so this avoids that function's documented clock
    mismatch). Flags a decision that came back suspiciously fast as a rubber-stamp candidate —
    never proof of one, just something a human reviewing this rollup should notice.

    Known limitation in this simulated environment: scripts/simulate_production_run.py's
    entire 10-cycle run executes in seconds of real wall-clock time, so every scripted
    approval in that run will flag here regardless of min_review_minutes — an artifact of the
    demo's compressed timeline, not a real finding. In a real deployment, decisions are made
    on their own real schedule and this figure is meaningful as-is."""
    from datetime import datetime as _datetime
    flags = []
    for bundle in incidents_module.list_incidents():
        if bundle["status"] not in ("approved", "rejected") or not bundle.get("reviewed_at"):
            continue
        created = _datetime.fromisoformat(bundle["created_at"])
        reviewed = _datetime.fromisoformat(bundle["reviewed_at"])
        minutes = (reviewed - created).total_seconds() / 60
        flags.append({
            "incident_id": bundle["incident_id"], "status": bundle["status"],
            "review_minutes": round(minutes, 2),
            "rubber_stamp_candidate": minutes < min_review_minutes,
        })
    return flags


def security_scan_summary() -> dict[str, Any]:
    """Pure rollup, zero new incident-log data: reads security_quality_events directly out of
    the fixed data/layer_metrics/*.json input files (same treatment as
    list_companies_with_history reading real files) and counts how many pii_scan/injection_scan
    events were present across the whole portfolio, vs. how many pulse/pii_scan.py and
    pulse/injection_monitoring.py actually flagged for real when the simulation ran."""
    from pulse import injection_monitoring, pii_scan

    totals = {"pii_scans_run": 0, "pii_detected": 0,
              "injection_scans_run": 0, "injection_marker_hits": 0}
    if not LAYER_METRICS_DIR.exists():
        return totals
    for path in sorted(LAYER_METRICS_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for cycle in data.get("cycles", {}).values():
            for event in cycle.get("security_quality_events", []):
                if event.get("type") == "pii_scan":
                    totals["pii_scans_run"] += 1
                    if pii_scan.scan(event.get("text", "")):
                        totals["pii_detected"] += 1
                elif event.get("type") == "injection_scan":
                    totals["injection_scans_run"] += 1
                    if injection_monitoring.scan(event.get("text", "")):
                        totals["injection_marker_hits"] += 1
    return totals


def system_health_summary() -> dict[str, Any]:
    """One rollup combining all of the above, for the dashboard's system-health panel."""
    companies = list_companies_with_history()
    return {
        "incident_rates": incident_rate_by_kind_and_tier(),
        "approval_turnaround": approval_turnaround(),
        "companies_tracked": companies,
        "schema_compliance": [schema_compliance_rate(cid) for cid in companies],
        "approval_quality_flags": approval_quality_flags(),
        "security_scan_summary": security_scan_summary(),
        "unexpected_tool_calls": {
            agent: calls for agent in EXPECTED_TOOLS
            if (calls := unexpected_tool_calls(agent))
        },
    }
