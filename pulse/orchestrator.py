"""Drives one sprint cycle. The only module that calls append_trend_entry (via
mcp_server.tools_impl) — never an agent directly, and never fed raw MCP response text, only
an agent's own validated structured output (see CLAUDE.md's guardrails section).

Since no live `claude` CLI session is available in this build, the *tool-fetching* half of
each cycle is real (this module really calls mcp_server.tools_impl, which really hits
pulse/trend_store.py, real layer_metrics files, and logs to the real audit log with a real
per-company call budget) — only the *agent classification* half is supplied as a
pre-computed structured output by the caller (scripts/simulate_production_run.py), standing
in for what a live subagent invocation would have returned. Everything downstream of that
input — schema validation, the assessment_failed default, the CHARTER combination rule,
destructive-layer-change detection, model boundary detection, risk scoring, incident
creation, rollback, and notification dispatch — is real code making its own decisions from
that input, not scripted.
"""

from __future__ import annotations

from typing import Any

from mcp_server import tools_impl
from pulse import (
    agent_loop_detection,
    canary_comparison,
    company_registry,
    company_rollback,
    human_approval,
    incidents,
    injection_monitoring,
    layer_versioning,
    model_boundary,
    notifications,
    pii_scan,
    policy_rules,
    registry,
    risk_scoring,
    schema_validator,
    soft_fix,
)
from pulse.retry import CallBudget

# Thresholds for the continuous per-cycle metrics — same warning/breach shape as
# classify_slo_status, applied to the fraction of interactions users themselves escalated to a
# human, independent of what the classifying agent says about the cycle.
USER_ESCALATION_THRESHOLDS = {"warning_at_or_above": 8.0, "breach_at_or_above": 15.0}

GOAL_DRIFT_SCHEMA = {
    "type": "object",
    "required": ["raw_classification", "rationale"],
    "properties": {
        "raw_classification": {"type": "string", "enum": ["on_charter", "watch", "drifted"]},
        "rationale": {"type": "string"},
    },
}

CHANGE_IMPACT_SCHEMA = {
    "type": "object",
    "required": ["read", "rationale"],
    "properties": {
        "read": {"type": "string", "enum": ["attributable", "noise"]},
        "rationale": {"type": "string"},
    },
}

SLO_TRAJECTORY_SCHEMA = {
    "type": "object",
    "required": ["trajectory", "rationale"],
    "properties": {
        "trajectory": {"type": "string", "enum": ["improving", "stable", "deteriorating"]},
        "rationale": {"type": "string"},
    },
}

MODEL_BOUNDARY_JUDGMENT_SCHEMA = {
    "type": "object",
    "required": ["judgment", "rationale"],
    "properties": {
        "judgment": {"type": "string", "enum": ["genuine_change", "model_interpretation_noise", "uncertain"]},
        "rationale": {"type": "string"},
    },
}

POLICY_COMPLIANCE_SCHEMA = {
    "type": "object",
    "required": ["compliant", "matched_clause_titles", "rationale"],
    "properties": {
        "compliant": {"type": "boolean"},
        "matched_clause_titles": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
}

GROUNDEDNESS_SCHEMA = {
    "type": "object",
    "required": ["judgment", "rationale"],
    "properties": {
        "judgment": {"type": "string", "enum": ["grounded", "unsupported", "fabricated"]},
        "rationale": {"type": "string"},
    },
}


def _combine_charter_classification(raw_classification: str, change_read: str) -> str:
    """Deterministic combination rule (orchestrator code, not an LLM call):
    change-impact-synthesizer acts as the causal-attribution gate on goal-drift-tracker's raw
    charter read. If the finding is noise (no attributable layer-change event behind it),
    whatever watch/drifted read goal-drift-tracker flagged is explained away — on_charter
    stands. If it's attributable to a real change event, goal-drift-tracker's raw read passes
    through unchanged. This is exactly why a change-impact-synthesizer regression that stops
    correctly filtering noise causes false drifted calls: the gate stops gating, not because
    goal-drift-tracker changed."""
    if change_read == "attributable":
        return raw_classification
    return "on_charter"


def classify_slo_status(value: float, thresholds: dict[str, float]) -> str:
    """Pure deterministic error-budget math — never an LLM judgment. slo-risk-tracker's
    'trajectory' output is trajectory commentary only; this function decides the label."""
    if value >= thresholds["breach_at_or_above"]:
        return "breach"
    if value >= thresholds["warning_at_or_above"]:
        return "warning"
    return "compliant"


def cycle_end_date(cycle: str):
    """Synthetic bi-weekly sprint calendar: sprint N of a year ends on day (N*14 - 1) of that
    year — not a real calendar, just monotonic and stable enough for SLA/business-day math."""
    from datetime import date, timedelta
    year_str, s_str = cycle.split("-S")
    sprint_num = int(s_str)
    base = date(int(year_str), 1, 1)
    return base + timedelta(days=sprint_num * 14 - 1)


def _detect_company_agent_findings(metrics: dict[str, Any], company_id: str) -> list[risk_scoring.RiskFinding]:
    """The actual subject of monitoring: risk-tiered findings for the MONITORED COMPANY's own
    internal agents (e.g. Meridian's resolution-agent), read straight off this cycle's
    company_agent_events — never Stack Sentinel's own classifiers (see
    pulse/risk_scoring.check_company_agent_regression's docstring for that distinction)."""
    findings = []
    for event in metrics.get("company_agent_events", []):
        finding = risk_scoring.check_company_agent_regression(
            event["risk_tier"], company_id, event["agent"], event.get("description", ""),
        )
        if finding is not None:
            findings.append(finding)
    return findings


def _detect_destructive_events(
    previous_entry: dict[str, Any] | None, metrics: dict[str, Any],
) -> list[layer_versioning.LayerChangeEvent]:
    prev_layers = previous_entry["metric_snapshot"]["layers"] if previous_entry else None
    curr_layers = metrics["layers"]
    events = []
    for layer in layer_versioning.LAYER_VERSION_FIELDS:
        event = layer_versioning.detect_layer_change(layer, prev_layers, curr_layers)
        if event is not None and event.change_kind == "destructive_change_candidate":
            events.append(event)
    return events


def _detect_continuous_metric_findings(
    metrics: dict[str, Any], history: list[dict[str, Any]],
) -> list[risk_scoring.RiskFinding]:
    """Cost, context-window pressure, and user-escalation rate — evaluated every cycle from
    this cycle's operational_health plus (for cost) the bounded trend-history window already
    fetched for this cycle, exactly the same shape as SLO error-budget math: a threshold or
    trailing-average comparison, never an LLM judgment."""
    health = metrics.get("operational_health", {})
    findings: list[risk_scoring.RiskFinding] = []

    cost = health.get("llm_cost_usd")
    if cost is not None:
        past_costs = [
            h["metric_snapshot"].get("operational_health", {}).get("llm_cost_usd")
            for h in history
        ]
        past_costs = [c for c in past_costs if c is not None]
        trailing_avg = sum(past_costs) / len(past_costs) if past_costs else None
        finding = risk_scoring.check_cost_anomaly(cost, trailing_avg)
        if finding is not None:
            findings.append(finding)

    utilization = health.get("context_utilization_pct")
    if utilization is not None:
        finding = risk_scoring.check_context_pressure(utilization, health.get("context_truncated", False))
        if finding is not None:
            findings.append(finding)

    escalation_rate = health.get("user_escalation_rate_pct")
    if escalation_rate is not None:
        finding = risk_scoring.check_user_escalation_spike(escalation_rate, USER_ESCALATION_THRESHOLDS)
        if finding is not None:
            findings.append(finding)

    return findings


def _detect_security_quality_findings(
    metrics: dict[str, Any], groundedness_outputs: dict[tuple[str, str, int], dict[str, Any]],
    company_id: str, cycle: str,
) -> list[risk_scoring.RiskFinding]:
    """Discrete per-cycle events, each backed by a real deterministic detector (pii_scan.py,
    injection_monitoring.py, agent_loop_detection.py, canary_comparison.py) except
    groundedness_check, the one genuine semantic-judgment case, sourced from the scripted
    groundedness-checker output keyed by (company_id, cycle, event_index) — same shape as
    policy_compliance_outputs. A missing or malformed groundedness output is simply skipped
    (no finding) rather than failing the whole cycle: this is a secondary check layered on top
    of the cycle's primary classification, which already has its own ONE-default handling."""
    behavior_incidents_this_cycle = bool(metrics.get("behavior_incidents"))
    findings: list[risk_scoring.RiskFinding] = []

    for i, event in enumerate(metrics.get("security_quality_events", [])):
        etype = event.get("type")
        finding: risk_scoring.RiskFinding | None = None

        if etype == "pii_scan":
            finding = risk_scoring.check_pii_exposure(pii_scan.scan(event.get("text", "")))
        elif etype == "injection_scan":
            marker_hits = injection_monitoring.scan(event.get("text", ""))
            finding = risk_scoring.check_prompt_injection(
                marker_hits, succeeded=bool(marker_hits) and behavior_incidents_this_cycle,
            )
        elif etype == "agent_loop":
            repeat_count = agent_loop_detection.max_repeat_run(event.get("call_sequence", []))
            finding = risk_scoring.check_agent_loop(repeat_count)
            if finding is not None:
                finding.detail["agents_involved"] = event.get("agents_involved", [])
        elif etype == "canary_comparison":
            diverged = canary_comparison.decisions_diverge(
                event.get("old_decision"), event.get("new_decision"),
            )
            finding = risk_scoring.check_canary_divergence(diverged)
            if finding is not None:
                finding.detail["agent"] = event.get("agent")
        elif etype == "groundedness_check":
            output = groundedness_outputs.get((company_id, cycle, i))
            if output is not None and not schema_validator.validate(output, GROUNDEDNESS_SCHEMA):
                finding = risk_scoring.check_groundedness(output["judgment"])
                if finding is not None:
                    finding.detail["agent"] = event.get("agent")

        if finding is not None:
            findings.append(finding)

    return findings


def run_charter_company_cycle(
    *, company_id: str, cycle: str, goal_drift_output: dict[str, Any] | None,
    change_impact_output: dict[str, Any] | None, budget: CallBudget,
    model_override: str | None = None,
    groundedness_outputs: dict[tuple[str, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One CHARTER-tracked company's sprint cycle. Returns {"entry", "failed", "boundary_kind",
    "previous_entry", "destructive_events", "company_agent_findings",
    "continuous_metric_findings", "security_quality_findings"}.

    model_override: for the rare, real case where the model that actually produced this
    specific call differs from what the registry's active bundle documents as the intended
    pin (e.g. a provider-side snapshot resolving differently for one request) — the entry
    always records what ACTUALLY happened, never re-derived from the registry after the
    fact. Almost always None; the simulation uses this exactly once, for the scripted
    model-boundary scenario."""
    groundedness_outputs = groundedness_outputs or {}
    charter_caller = {"agent": "goal-drift-tracker", "agent_version": "v1"}

    budget.consume("get_system_charter")
    tools_impl.get_system_charter(company_id, caller=charter_caller)
    budget.consume("get_system_metrics")
    metrics = tools_impl.get_system_metrics(company_id, cycle, caller=charter_caller)
    budget.consume("get_trend_history")
    history = tools_impl.get_trend_history(company_id, limit=6, caller=charter_caller)
    previous_entry = history[-1] if history else None

    cis_active = registry.get_active("change-impact-synthesizer")
    cis_version = cis_active["version"] if cis_active else "unknown"
    cis_model = model_override or (cis_active["model"] if cis_active else "unknown")

    errors: list[str] = []
    if goal_drift_output is None:
        errors.append("goal-drift-tracker produced no output")
    else:
        errors += [f"goal_drift_output: {e}" for e in schema_validator.validate(goal_drift_output, GOAL_DRIFT_SCHEMA)]
    if change_impact_output is None:
        errors.append("change-impact-synthesizer produced no output")
    else:
        errors += [f"change_impact_output: {e}" for e in schema_validator.validate(change_impact_output, CHANGE_IMPACT_SCHEMA)]

    destructive_events = _detect_destructive_events(previous_entry, metrics)
    company_agent_findings = _detect_company_agent_findings(metrics, company_id)
    continuous_metric_findings = _detect_continuous_metric_findings(metrics, history)
    security_quality_findings = _detect_security_quality_findings(
        metrics, groundedness_outputs, company_id, cycle,
    )

    if errors:
        entry = tools_impl.append_trend_entry({
            "company_id": company_id, "cycle": cycle, "monitoring_track": "CHARTER",
            "classifying_agent": "change-impact-synthesizer", "agent_version": cis_version, "model": cis_model,
            "metric_snapshot": metrics, "classification": "assessment_failed",
            "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
        }, caller=charter_caller)
        return {"entry": entry, "failed": True, "boundary_kind": None, "previous_entry": previous_entry,
                "destructive_events": destructive_events, "company_agent_findings": company_agent_findings,
                "continuous_metric_findings": continuous_metric_findings,
                "security_quality_findings": security_quality_findings}

    final_classification = _combine_charter_classification(goal_drift_output["raw_classification"], change_impact_output["read"])
    entry = tools_impl.append_trend_entry({
        "company_id": company_id, "cycle": cycle, "monitoring_track": "CHARTER",
        "classifying_agent": "change-impact-synthesizer", "agent_version": cis_version, "model": cis_model,
        "metric_snapshot": metrics, "classification": final_classification,
        "rationale": (
            f"goal-drift-tracker raw read: {goal_drift_output['raw_classification']} "
            f"({goal_drift_output['rationale']}) | change-impact-synthesizer: {change_impact_output['read']} "
            f"({change_impact_output['rationale']})"
        ),
        "contributing_assessments": [
            {"agent": "goal-drift-tracker", "version": "v1",
             "raw_classification": goal_drift_output["raw_classification"], "rationale": goal_drift_output["rationale"]},
            {"agent": "change-impact-synthesizer", "version": cis_version, "model": cis_model,
             "read": change_impact_output["read"], "rationale": change_impact_output["rationale"]},
        ],
    }, caller=charter_caller)

    boundary = model_boundary.detect_boundary(previous_entry, entry) if previous_entry else None

    newly_drifted = final_classification == "drifted" and (
        previous_entry is None or previous_entry["classification"] != "drifted"
    )
    if newly_drifted:
        notifications.dispatch_drifted_review(
            company_id=company_id, company_name=tools_impl.get_company_display_name(company_id),
            cycle=cycle, as_of_date=cycle_end_date(cycle), rationale=entry["rationale"],
        )

    return {"entry": entry, "failed": False, "boundary_kind": boundary, "previous_entry": previous_entry,
            "destructive_events": destructive_events, "company_agent_findings": company_agent_findings,
            "continuous_metric_findings": continuous_metric_findings,
            "security_quality_findings": security_quality_findings}


def run_slo_company_cycle(
    *, company_id: str, cycle: str, metric_field: str, thresholds: dict[str, float],
    slo_trajectory_output: dict[str, Any] | None, budget: CallBudget,
    groundedness_outputs: dict[tuple[str, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One SLO-tracked company's sprint cycle. Classification is deterministic error-budget
    math; slo_trajectory_output only supplies trajectory commentary for the rationale."""
    groundedness_outputs = groundedness_outputs or {}
    slo_caller = {"agent": "slo-risk-tracker", "agent_version": "v1"}

    budget.consume("get_slo_agreement")
    tools_impl.get_slo_agreement(company_id, caller=slo_caller)
    budget.consume("get_system_metrics")
    metrics = tools_impl.get_system_metrics(company_id, cycle, caller=slo_caller)
    budget.consume("get_trend_history")
    history = tools_impl.get_trend_history(company_id, limit=6, caller=slo_caller)
    previous_entry = history[-1] if history else None

    slo_active = registry.get_active("slo-risk-tracker")
    slo_version = slo_active["version"] if slo_active else "unknown"
    slo_model = slo_active["model"] if slo_active else "unknown"

    errors: list[str] = []
    if slo_trajectory_output is None:
        errors.append("slo-risk-tracker produced no output")
    else:
        errors += [f"slo_trajectory_output: {e}" for e in schema_validator.validate(slo_trajectory_output, SLO_TRAJECTORY_SCHEMA)]

    destructive_events = _detect_destructive_events(previous_entry, metrics)
    company_agent_findings = _detect_company_agent_findings(metrics, company_id)
    continuous_metric_findings = _detect_continuous_metric_findings(metrics, history)
    security_quality_findings = _detect_security_quality_findings(
        metrics, groundedness_outputs, company_id, cycle,
    )

    if errors:
        entry = tools_impl.append_trend_entry({
            "company_id": company_id, "cycle": cycle, "monitoring_track": "SLO",
            "classifying_agent": "slo-risk-tracker", "agent_version": slo_version, "model": slo_model,
            "metric_snapshot": metrics, "classification": "assessment_failed",
            "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
        }, caller=slo_caller)
        return {"entry": entry, "failed": True, "boundary_kind": None, "previous_entry": previous_entry,
                "destructive_events": destructive_events, "company_agent_findings": company_agent_findings,
                "continuous_metric_findings": continuous_metric_findings,
                "security_quality_findings": security_quality_findings}

    value = metrics["operational_health"][metric_field]
    classification = classify_slo_status(value, thresholds)
    entry = tools_impl.append_trend_entry({
        "company_id": company_id, "cycle": cycle, "monitoring_track": "SLO",
        "classifying_agent": "slo-risk-tracker", "agent_version": slo_version, "model": slo_model,
        "metric_snapshot": metrics, "classification": classification,
        "rationale": (
            f"{metric_field}={value} vs warning>={thresholds['warning_at_or_above']}, "
            f"breach>={thresholds['breach_at_or_above']} -> {classification}. Trajectory "
            f"({slo_trajectory_output['trajectory']}): {slo_trajectory_output['rationale']}"
        ),
        "contributing_assessments": [
            {"agent": "slo-risk-tracker", "version": slo_version, "model": slo_model,
             "trajectory": slo_trajectory_output["trajectory"], "rationale": slo_trajectory_output["rationale"]},
        ],
    }, caller=slo_caller)

    boundary = model_boundary.detect_boundary(previous_entry, entry) if previous_entry else None
    return {"entry": entry, "failed": False, "boundary_kind": boundary, "previous_entry": previous_entry,
            "destructive_events": destructive_events, "company_agent_findings": company_agent_findings,
            "continuous_metric_findings": continuous_metric_findings,
            "security_quality_findings": security_quality_findings}


def _policy_compliance_query(kind: str, risk_tier: str, routing: str, justification: str) -> str:
    return f"{kind} risk_tier={risk_tier} routing={routing}: {justification}"


def _check_policy_compliance(
    *, company_ids: list[str], kind: str, risk_tier: str, routing: str, justification: str,
    company_cycle_results: dict[str, dict[str, Any]],
    policy_compliance_outputs: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Runs policy-compliance-checker once PER COMPANY named on an incident — never once for
    the whole incident — because search_company_policy is scoped to exactly one company's own
    policy document at a time (the same discipline goal-drift-tracker applies to that
    company's own charter boundaries, not a shared one). Each per-company invocation is
    grounded in the real contributing agent input/output that produced this cycle's
    classification (goal-drift-tracker / change-impact-synthesizer / slo-risk-tracker's raw
    reads, as recorded on the trend entry) — not just the bare classification label — plus one
    company-scoped and one shared policy search, matching the hard 2-call cap in
    .claude/agents/policy-compliance-checker.md.

    policy_compliance_outputs is keyed by (company_id, kind) — the scripted stand-in for what
    a live policy-compliance-checker invocation would have returned for that (company,
    incident-kind) pair this cycle. Missing or malformed output gets the same ONE default as
    every other agent in this system: checked=False, compliant=None, no retry.
    """
    pcc_active = registry.get_active("policy-compliance-checker")
    policy_caller = {"agent": "policy-compliance-checker",
                      "agent_version": pcc_active["version"] if pcc_active else "unknown"}
    query = _policy_compliance_query(kind, risk_tier, routing, justification)

    results: dict[str, dict[str, Any]] = {}
    for cid in company_ids:
        budget = CallBudget(max_calls=2)
        budget.consume("search_company_policy")
        company_clauses = tools_impl.search_company_policy(cid, query, k=1, caller=policy_caller)
        budget.consume("search_policy")
        shared_clauses = tools_impl.search_policy(query, k=1, caller=policy_caller)

        contributing = company_cycle_results.get(cid, {}).get("entry", {}).get("contributing_assessments", [])
        output = policy_compliance_outputs.get((cid, kind))

        base = {
            "matched_clause_titles": [], "company_clauses": company_clauses,
            "shared_clauses": shared_clauses, "contributing_assessments": contributing,
        }
        if output is None:
            results[cid] = {**base, "checked": False, "compliant": None,
                             "rationale": "policy-compliance-checker produced no output for this "
                                          "(company, kind) pair this cycle — ONE default applied, no retry."}
            continue
        errors = schema_validator.validate(output, POLICY_COMPLIANCE_SCHEMA)
        if errors:
            results[cid] = {**base, "checked": False, "compliant": None,
                             "rationale": "policy-compliance-checker output failed schema validation: " + "; ".join(errors)}
            continue
        results[cid] = {
            **base, "checked": True, "compliant": output["compliant"],
            "matched_clause_titles": output["matched_clause_titles"], "rationale": output["rationale"],
        }
    return results


def _apply_policy_check(
    incident: dict[str, Any], finding: risk_scoring.RiskFinding, *, as_of_date,
    company_cycle_results: dict[str, dict[str, Any]],
    policy_compliance_outputs: dict[tuple[str, str], dict[str, Any]],
    cycle_incidents: list[dict[str, Any]], cycle_notifications: list[dict[str, Any]],
) -> None:
    """Checks a just-created incident's routing decision against policy (real search calls,
    real schema validation, per company) and attaches the result to the incident record. A
    non-compliant read never silently corrects or blocks the original incident's own routing
    (that's already been decided by risk_scoring, deterministically) — it creates a SEPARATE
    policy_violation incident via risk_scoring.check_policy_violation, routed to human_review,
    same as every other kind this system cannot safely auto-resolve."""
    policy_check = _check_policy_compliance(
        company_ids=incident["company_ids"], kind=finding.kind, risk_tier=finding.risk_tier,
        routing=finding.routing, justification=finding.justification,
        company_cycle_results=company_cycle_results, policy_compliance_outputs=policy_compliance_outputs,
    )
    incidents.attach_policy_check(incident["incident_id"], policy_check)
    incident["policy_check"] = policy_check

    pcc_active = registry.get_active("policy-compliance-checker")
    for cid, check in policy_check.items():
        if not (check["checked"] and check["compliant"] is False):
            continue
        violation = risk_scoring.check_policy_violation(True, detail=check["rationale"])
        violation_incident = incidents.create_incident(
            kind=violation.kind, company_ids=[cid],
            agent_version=pcc_active["version"] if pcc_active else "unknown",
            model=pcc_active["model"] if pcc_active else "unknown",
            input_snapshot={"source_incident_id": incident["incident_id"], "source_kind": finding.kind,
                             "matched_clause_titles": check["matched_clause_titles"]},
            output_snapshot={"compliant": False}, risk_tier=violation.risk_tier, routing=violation.routing,
            detected_at=as_of_date.isoformat(), remediation_detail=violation.justification,
        )
        cycle_incidents.append(violation_incident)
        cycle_notifications.extend(notifications.dispatch_for_incident(violation_incident))


def _route_finding(
    finding: risk_scoring.RiskFinding, *, company_ids: list[str], agent_version: str, model: str,
    input_snapshot: dict[str, Any], output_snapshot: dict[str, Any], as_of_date,
    company_cycle_results: dict[str, dict[str, Any]],
    policy_compliance_outputs: dict[tuple[str, str], dict[str, Any]],
    cycle_incidents: list[dict[str, Any]], cycle_notifications: list[dict[str, Any]],
    counterfactual: dict[str, Any] | None = None,
    auto_rollback_fn=None, auto_rollback_actor: str | None = None, auto_rollback_note: str | None = None,
) -> dict[str, Any]:
    """The uniform incident lifecycle used by EVERY finding source in this module, regardless
    of kind: create the incident, perform the finding's own prescribed action
    (auto_rollback via auto_rollback_fn — the only two real callers today are
    pulse/soft_fix.py for Stack Sentinel's own agents and pulse/company_rollback.py for a
    monitored company's own agent, never anything else; pending_human_approval's never-acts
    gate; human_review takes no further action here beyond recording the incident), append +
    dispatch, then run the real per-company policy-compliance check against the routing
    decision (_apply_policy_check). This exists because this system now has 12 distinct
    finding kinds feeding into the exact same lifecycle — without it, each kind would need its
    own near-duplicate 15-line block."""
    incident = incidents.create_incident(
        kind=finding.kind, company_ids=company_ids, agent_version=agent_version, model=model,
        input_snapshot=input_snapshot, output_snapshot=output_snapshot,
        risk_tier=finding.risk_tier, routing=finding.routing,
        detected_at=as_of_date.isoformat(), remediation_detail=finding.justification,
        counterfactual=counterfactual,
    )

    if finding.routing == "auto_rollback":
        if auto_rollback_fn is None:
            raise ValueError(f"finding kind={finding.kind!r} routed to auto_rollback with no auto_rollback_fn wired")
        rollback_pointer = auto_rollback_fn()
        incidents.record_human_review(
            incident["incident_id"], resolved_by=auto_rollback_actor,
            human_note=auto_rollback_note or f"Auto-rolled back to {rollback_pointer['active_version']}.",
            new_status="auto_resolved",
        )
    elif finding.routing == "pending_human_approval":
        # human_approval.py never executes anything — this call only formally records that
        # the underlying action has NOT been taken and is pending a human decision.
        gate_result = human_approval.gate_destructive_action(finding.justification)
        assert gate_result["action_taken"] is False

    cycle_incidents.append(incident)
    cycle_notifications.extend(notifications.dispatch_for_incident(incident))
    _apply_policy_check(
        incident, finding, as_of_date=as_of_date, company_cycle_results=company_cycle_results,
        policy_compliance_outputs=policy_compliance_outputs,
        cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
    )
    return incident


FLAGGED_CLASSIFICATIONS = {"drifted", "warning", "breach"}


def run_portfolio_cycle(
    *, cycle: str, as_of_date, portfolio_size: int, company_cycle_results: dict[str, dict[str, Any]],
    model_boundary_judgments: dict[str, dict[str, Any]] | None = None,
    systemic_spike_counterfactuals: dict[str, dict[str, Any]] | None = None,
    policy_compliance_outputs: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """After every company's per-company cycle for this cycle is done: cross-company risk
    assessment, incident creation, rollback, and notification dispatch. This is where
    systemic-flag-spike (inherently cross-company), model-boundary routing, and
    destructive-layer-change routing actually fire.

    model_boundary_judgments: {company_id: model-boundary-interpreter output} for any company
    whose per-company cycle returned a non-None boundary_kind this cycle.
    systemic_spike_counterfactuals: {company_id: what the last-known-good version would have
    said on the identical input}, for at least one company affected by a systemic-flag-spike
    this cycle — attached directly to the incident's replay bundle at creation time.
    policy_compliance_outputs: {(company_id, incident_kind): policy-compliance-checker output}
    — every incident created below is also checked, per company named on it, against that
    company's own policy document AND the shared corpus (see _apply_policy_check). A missing
    entry here is not an error — it's read the same as a real invocation that produced no
    output, and gets the same ONE assessment_failed-style default as every other agent.
    """
    model_boundary_judgments = model_boundary_judgments or {}
    systemic_spike_counterfactuals = systemic_spike_counterfactuals or {}
    policy_compliance_outputs = policy_compliance_outputs or {}

    flagged_company_ids = [
        cid for cid, result in company_cycle_results.items()
        if not result["failed"] and result["entry"]["classification"] in FLAGGED_CLASSIFICATIONS
    ]

    # Systemic-flag-spike is specifically the fingerprint of an AGENT-VERSION regression —
    # it must only count companies whose classification actually passed through the
    # versioned agent being tracked (change-impact-synthesizer, for CHARTER). An SLO
    # "warning" is pure deterministic math (orchestrator.classify_slo_status) with no LLM
    # anywhere in its path, so it can never be evidence of an agent regression and must never
    # be co-mingled into this count — otherwise a genuine, unrelated SLO flag occurring in
    # the same cycle as one real CHARTER flag could falsely trip the spike threshold. This is
    # exactly the false-positive the systemic-flag-spike rule exists to NOT produce.
    spike_candidate_ids = [
        cid for cid in flagged_company_ids
        if company_cycle_results[cid]["entry"]["classifying_agent"] == "change-impact-synthesizer"
    ]

    cycle_incidents: list[dict[str, Any]] = []
    cycle_notifications: list[dict[str, Any]] = []

    # --- systemic flag spike -> auto-rollback (Stack Sentinel's own agent) -------------
    spike_finding = risk_scoring.check_systemic_flag_spike(spike_candidate_ids, portfolio_size)
    if spike_finding is not None:
        cis_active = registry.get_active("change-impact-synthesizer")
        _route_finding(
            spike_finding, company_ids=spike_candidate_ids,
            agent_version=cis_active["version"], model=cis_active["model"],
            input_snapshot={cid: company_cycle_results[cid]["entry"]["metric_snapshot"] for cid in spike_candidate_ids},
            output_snapshot={cid: company_cycle_results[cid]["entry"]["classification"] for cid in spike_candidate_ids},
            as_of_date=as_of_date, company_cycle_results=company_cycle_results,
            policy_compliance_outputs=policy_compliance_outputs,
            cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
            counterfactual=systemic_spike_counterfactuals or None,
            # soft_fix.py is the ONLY module permitted to perform this rollback itself.
            auto_rollback_fn=lambda: soft_fix.auto_rollback_to_last_known_good(
                "change-impact-synthesizer", reason=spike_finding.justification,
            ),
            auto_rollback_actor=soft_fix.ROLLBACK_ACTOR,
            auto_rollback_note="Auto-rolled back change-impact-synthesizer.",
        )

    # --- model boundary ambiguity -> human review --------------------------------------
    for cid, result in company_cycle_results.items():
        if result["failed"] or result["boundary_kind"] is None:
            continue
        finding = risk_scoring.check_model_boundary_ambiguity(result["boundary_kind"])
        if finding is None:
            continue
        judgment = model_boundary_judgments.get(cid)
        _route_finding(
            finding, company_ids=[cid],
            agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
            input_snapshot={"previous_entry": result["previous_entry"], "current_entry": result["entry"]},
            output_snapshot={"model_boundary_interpreter_judgment": judgment},
            as_of_date=as_of_date, company_cycle_results=company_cycle_results,
            policy_compliance_outputs=policy_compliance_outputs,
            cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
        )

    # --- destructive layer change -> pending human approval, never auto-executed -------
    for cid, result in company_cycle_results.items():
        for event in result.get("destructive_events", []):
            finding = risk_scoring.check_destructive_layer_change(event.change_kind, event.layer)
            if finding is None:
                continue
            _route_finding(
                finding, company_ids=[cid],
                agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
                input_snapshot={"layer": event.layer, "change_event": event.change_event,
                                 "from_version": event.from_version, "to_version": event.to_version},
                output_snapshot={},
                as_of_date=as_of_date, company_cycle_results=company_cycle_results,
                policy_compliance_outputs=policy_compliance_outputs,
                cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
            )

    # --- company-agent regression -> risk-tiered: low/medium auto-rolls-back the company's
    # own agent with no human in the loop; high/critical is never auto-executed, gated for an
    # explicit human decision instead. This is the actual subject of this system — versioning
    # and rolling back the MONITORED COMPANIES' own agents, not Stack Sentinel's own six
    # classifiers (those are defended separately, by model_boundary.py / systemic-flag-spike
    # above, for a different reason: catching drift in Stack Sentinel's own judgment).
    for cid, result in company_cycle_results.items():
        for finding in result.get("company_agent_findings", []):
            agent = finding.detail["agent"]
            _route_finding(
                finding, company_ids=[cid],
                agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
                input_snapshot={"company_id": cid, "agent": agent, "risk_tier": finding.risk_tier},
                output_snapshot={},
                as_of_date=as_of_date, company_cycle_results=company_cycle_results,
                policy_compliance_outputs=policy_compliance_outputs,
                cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
                auto_rollback_fn=lambda cid=cid, agent=agent, finding=finding: company_rollback.auto_rollback_company_agent(
                    cid, agent, reason=finding.justification,
                ),
                auto_rollback_actor=company_rollback.ROLLBACK_ACTOR,
                auto_rollback_note=f"Auto-rolled back {cid}/{agent}.",
            )

    # --- continuous per-cycle metrics (cost, context pressure, user-escalation) -> always
    # human_review, nothing here is auto-fixable by this system. ------------------------
    for cid, result in company_cycle_results.items():
        for finding in result.get("continuous_metric_findings", []):
            _route_finding(
                finding, company_ids=[cid],
                agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
                input_snapshot={"company_id": cid, **finding.detail}, output_snapshot={},
                as_of_date=as_of_date, company_cycle_results=company_cycle_results,
                policy_compliance_outputs=policy_compliance_outputs,
                cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
            )

    # --- discrete security/quality events (PII exposure, prompt injection, agent loops,
    # canary divergence, groundedness failures) — each backed by a real deterministic
    # detector in pulse/ (or, for groundedness, the one new agent), never a fabricated verdict.
    for cid, result in company_cycle_results.items():
        for finding in result.get("security_quality_findings", []):
            rollback_kwargs: dict[str, Any] = {}
            if finding.kind == "agent_loop_detected" and finding.routing == "auto_rollback":
                agent = finding.detail["agents_involved"][0]
                rollback_kwargs = {
                    "auto_rollback_fn": lambda cid=cid, agent=agent, finding=finding: company_rollback.auto_rollback_company_agent(
                        cid, agent, reason=finding.justification,
                    ),
                    "auto_rollback_actor": company_rollback.ROLLBACK_ACTOR,
                    "auto_rollback_note": f"Auto-rolled back {cid}/{agent} after a detected hand-off loop.",
                }
            _route_finding(
                finding, company_ids=[cid],
                agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
                input_snapshot={"company_id": cid, **finding.detail}, output_snapshot={},
                as_of_date=as_of_date, company_cycle_results=company_cycle_results,
                policy_compliance_outputs=policy_compliance_outputs,
                cycle_incidents=cycle_incidents, cycle_notifications=cycle_notifications,
                **rollback_kwargs,
            )

    return {
        "cycle": cycle, "flagged_company_ids": flagged_company_ids,
        "incidents": cycle_incidents, "notifications": cycle_notifications,
    }


def check_rrb_escalation(company_id: str, cycle: str, as_of_date, trend_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic policy_rules check for the Reliability Review Board reporting clause.
    This is NOT a risk_scoring finding — it's a correctly-functioning escalation, not a
    system failure, so it dispatches directly rather than creating an incident. Returns the
    notification dispatch record if the clause is newly triggered, else None."""
    if not policy_rules.rrb_clause_triggered(trend_history):
        return None
    # Only dispatch once — the moment the streak first reaches the threshold, not every
    # subsequent cycle it stays at or above it (that would re-notify every cycle).
    streak = policy_rules.count_consecutive_warning_cycles(trend_history)
    if streak != policy_rules.CONSECUTIVE_WARNING_THRESHOLD_FOR_RRB:
        return None
    return notifications.dispatch_rrb_escalation(company_id=company_id, cycle=cycle, as_of_date=as_of_date)
