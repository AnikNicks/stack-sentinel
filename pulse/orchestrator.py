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
    company_registry,
    company_rollback,
    human_approval,
    incidents,
    layer_versioning,
    model_boundary,
    notifications,
    policy_rules,
    registry,
    risk_scoring,
    schema_validator,
    soft_fix,
)
from pulse.retry import CallBudget

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


def run_charter_company_cycle(
    *, company_id: str, cycle: str, goal_drift_output: dict[str, Any] | None,
    change_impact_output: dict[str, Any] | None, budget: CallBudget,
    model_override: str | None = None,
) -> dict[str, Any]:
    """One CHARTER-tracked company's sprint cycle. Returns {"entry", "failed", "boundary_kind",
    "previous_entry", "destructive_events"}.

    model_override: for the rare, real case where the model that actually produced this
    specific call differs from what the registry's active bundle documents as the intended
    pin (e.g. a provider-side snapshot resolving differently for one request) — the entry
    always records what ACTUALLY happened, never re-derived from the registry after the
    fact. Almost always None; the simulation uses this exactly once, for the scripted
    model-boundary scenario."""
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

    if errors:
        entry = tools_impl.append_trend_entry({
            "company_id": company_id, "cycle": cycle, "monitoring_track": "CHARTER",
            "classifying_agent": "change-impact-synthesizer", "agent_version": cis_version, "model": cis_model,
            "metric_snapshot": metrics, "classification": "assessment_failed",
            "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
        }, caller=charter_caller)
        return {"entry": entry, "failed": True, "boundary_kind": None, "previous_entry": previous_entry,
                "destructive_events": destructive_events, "company_agent_findings": company_agent_findings}

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
            "destructive_events": destructive_events, "company_agent_findings": company_agent_findings}


def run_slo_company_cycle(
    *, company_id: str, cycle: str, metric_field: str, thresholds: dict[str, float],
    slo_trajectory_output: dict[str, Any] | None, budget: CallBudget,
) -> dict[str, Any]:
    """One SLO-tracked company's sprint cycle. Classification is deterministic error-budget
    math; slo_trajectory_output only supplies trajectory commentary for the rationale."""
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

    if errors:
        entry = tools_impl.append_trend_entry({
            "company_id": company_id, "cycle": cycle, "monitoring_track": "SLO",
            "classifying_agent": "slo-risk-tracker", "agent_version": slo_version, "model": slo_model,
            "metric_snapshot": metrics, "classification": "assessment_failed",
            "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
        }, caller=slo_caller)
        return {"entry": entry, "failed": True, "boundary_kind": None, "previous_entry": previous_entry,
                "destructive_events": destructive_events, "company_agent_findings": company_agent_findings}

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
            "destructive_events": destructive_events, "company_agent_findings": company_agent_findings}


FLAGGED_CLASSIFICATIONS = {"drifted", "warning", "breach"}


def run_portfolio_cycle(
    *, cycle: str, as_of_date, portfolio_size: int, company_cycle_results: dict[str, dict[str, Any]],
    model_boundary_judgments: dict[str, dict[str, Any]] | None = None,
    systemic_spike_counterfactuals: dict[str, dict[str, Any]] | None = None,
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
    """
    model_boundary_judgments = model_boundary_judgments or {}
    systemic_spike_counterfactuals = systemic_spike_counterfactuals or {}

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

    # --- systemic flag spike -> auto-rollback -----------------------------------------
    spike_finding = risk_scoring.check_systemic_flag_spike(spike_candidate_ids, portfolio_size)
    if spike_finding is not None:
        cis_active = registry.get_active("change-impact-synthesizer")
        incident = incidents.create_incident(
            kind=spike_finding.kind, company_ids=spike_candidate_ids,
            agent_version=cis_active["version"], model=cis_active["model"],
            input_snapshot={cid: company_cycle_results[cid]["entry"]["metric_snapshot"] for cid in spike_candidate_ids},
            output_snapshot={cid: company_cycle_results[cid]["entry"]["classification"] for cid in spike_candidate_ids},
            risk_tier=spike_finding.risk_tier, routing=spike_finding.routing,
            detected_at=as_of_date.isoformat(), remediation_detail=spike_finding.justification,
            counterfactual=systemic_spike_counterfactuals or None,
        )
        # soft_fix.py is the ONLY module permitted to perform the rollback action itself;
        # notifications.py only ever sends messages about what happened, never acts.
        rollback_pointer = soft_fix.auto_rollback_to_last_known_good("change-impact-synthesizer", reason=spike_finding.justification)
        incidents.record_human_review(
            incident["incident_id"], resolved_by="pulse-auto-rollback",
            human_note=f"Auto-rolled back change-impact-synthesizer to {rollback_pointer['active_version']}.",
            new_status="auto_resolved",
        )
        cycle_incidents.append(incident)
        cycle_notifications += notifications.dispatch_for_incident(incident)

    # --- model boundary ambiguity -> human review --------------------------------------
    for cid, result in company_cycle_results.items():
        if result["failed"] or result["boundary_kind"] is None:
            continue
        finding = risk_scoring.check_model_boundary_ambiguity(result["boundary_kind"])
        if finding is None:
            continue
        judgment = model_boundary_judgments.get(cid)
        incident = incidents.create_incident(
            kind=finding.kind, company_ids=[cid],
            agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
            input_snapshot={"previous_entry": result["previous_entry"], "current_entry": result["entry"]},
            output_snapshot={"model_boundary_interpreter_judgment": judgment},
            risk_tier=finding.risk_tier, routing=finding.routing,
            detected_at=as_of_date.isoformat(), remediation_detail=finding.justification,
        )
        cycle_incidents.append(incident)
        cycle_notifications += notifications.dispatch_for_incident(incident)

    # --- destructive layer change -> pending human approval, never auto-executed -------
    for cid, result in company_cycle_results.items():
        for event in result.get("destructive_events", []):
            finding = risk_scoring.check_destructive_layer_change(event.change_kind, event.layer)
            if finding is None:
                continue
            incident = incidents.create_incident(
                kind=finding.kind, company_ids=[cid],
                agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
                input_snapshot={"layer": event.layer, "change_event": event.change_event,
                                 "from_version": event.from_version, "to_version": event.to_version},
                output_snapshot={},
                risk_tier=finding.risk_tier, routing=finding.routing,
                detected_at=as_of_date.isoformat(), remediation_detail=finding.justification,
            )
            # human_approval.py never executes anything — this call only formally records
            # that the underlying action has NOT been taken and is pending a human decision.
            gate_result = human_approval.gate_destructive_action(finding.justification)
            assert gate_result["action_taken"] is False
            cycle_incidents.append(incident)
            cycle_notifications += notifications.dispatch_for_incident(incident)

    # --- company-agent regression -> risk-tiered: low/medium auto-rolls-back the company's
    # own agent with no human in the loop; high/critical is never auto-executed, gated for an
    # explicit human decision instead. This is the actual subject of this system — versioning
    # and rolling back the MONITORED COMPANIES' own agents, not Stack Sentinel's own six
    # classifiers (those are defended separately, by model_boundary.py / systemic-flag-spike
    # above, for a different reason: catching drift in Stack Sentinel's own judgment).
    for cid, result in company_cycle_results.items():
        for finding in result.get("company_agent_findings", []):
            agent = finding.detail["agent"]
            incident = incidents.create_incident(
                kind=finding.kind, company_ids=[cid],
                agent_version=result["entry"]["agent_version"], model=result["entry"]["model"],
                input_snapshot={"company_id": cid, "agent": agent, "risk_tier": finding.risk_tier},
                output_snapshot={},
                risk_tier=finding.risk_tier, routing=finding.routing,
                detected_at=as_of_date.isoformat(), remediation_detail=finding.justification,
            )
            if finding.routing == "auto_rollback":
                rollback_pointer = company_rollback.auto_rollback_company_agent(cid, agent, reason=finding.justification)
                incidents.record_human_review(
                    incident["incident_id"], resolved_by=company_rollback.ROLLBACK_ACTOR,
                    human_note=f"Auto-rolled back {cid}/{agent} to {rollback_pointer['active_version']}.",
                    new_status="auto_resolved",
                )
            elif finding.routing == "pending_human_approval":
                # human_approval.py never executes anything — this only formally records that
                # the rollback has NOT happened and is pending an explicit human decision.
                gate_result = human_approval.gate_destructive_action(finding.justification)
                assert gate_result["action_taken"] is False
            cycle_incidents.append(incident)
            cycle_notifications += notifications.dispatch_for_incident(incident)

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
