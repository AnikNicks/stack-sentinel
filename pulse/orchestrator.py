"""Drives one quarterly cycle. The only module that calls append_trend_entry (via
mcp_server.tools_impl) — never an agent directly, and never fed raw MCP response text, only
an agent's own validated structured output (see CLAUDE.md's guardrails section).

Since no live `claude` CLI session is available in this build, the *tool-fetching* half of
each cycle is real (this module really calls mcp_server.tools_impl, which really hits
pulse/trend_store.py, real financials files, and logs to the real audit log with a real
per-company call budget) — only the *agent classification* half is supplied as a
pre-computed structured output by the caller (scripts/simulate_production_run.py), standing
in for what a live subagent invocation would have returned. Everything downstream of that
input — schema validation, the assessment_failed default, the PE/PD combination rule, model
boundary detection, risk scoring, incident creation, rollback, and notification dispatch —
is real code making its own decisions from that input, not scripted.
"""

from __future__ import annotations

from typing import Any

from mcp_server import tools_impl
from pulse import incidents, model_boundary, notifications, policy_rules, registry, risk_scoring, schema_validator, soft_fix
from pulse.retry import CallBudget

PE_THESIS_SCHEMA = {
    "type": "object",
    "required": ["raw_classification", "rationale"],
    "properties": {
        "raw_classification": {"type": "string", "enum": ["on_thesis", "watch", "off_thesis"]},
        "rationale": {"type": "string"},
    },
}

TREND_SYNTH_SCHEMA = {
    "type": "object",
    "required": ["read", "rationale"],
    "properties": {
        "read": {"type": "string", "enum": ["inflection", "noise"]},
        "rationale": {"type": "string"},
    },
}

PD_TRAJECTORY_SCHEMA = {
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
        "judgment": {"type": "string", "enum": ["business_driven", "model_interpretation_noise", "uncertain"]},
        "rationale": {"type": "string"},
    },
}


def _combine_pe_classification(raw_classification: str, trend_read: str) -> str:
    """Deterministic combination rule (orchestrator code, not an LLM call): trend-synthesizer
    acts as the noise-filter gate on pe-thesis-tracker's raw thesis read. If the movement is
    noise, whatever dip pe-thesis-tracker flagged is explained away — on_thesis stands. If
    it's a genuine inflection, pe-thesis-tracker's raw read passes through unchanged. This is
    exactly why a trend-synthesizer regression that stops correctly filtering noise causes
    false off_thesis calls: the gate stops gating, not because pe-thesis-tracker changed."""
    if trend_read == "inflection":
        return raw_classification
    return "on_thesis"


def classify_pd_covenant(ratio: float, thresholds: dict[str, float]) -> str:
    """Pure deterministic covenant math — never an LLM judgment. pd-covenant-tracker's
    'trajectory' output is trajectory commentary only; this function decides the label."""
    if ratio >= thresholds["breach_at_or_above"]:
        return "breach"
    if ratio >= thresholds["warning_at_or_above"]:
        return "warning"
    return "compliant"


def run_pe_company_cycle(
    *, company_id: str, quarter: str, pe_thesis_output: dict[str, Any] | None,
    trend_synth_output: dict[str, Any] | None, budget: CallBudget,
    model_override: str | None = None,
) -> dict[str, Any]:
    """One PE company's quarterly cycle. Returns {"entry", "failed", "boundary_kind",
    "previous_entry"}.

    model_override: for the rare, real case where the model that actually produced this
    specific call differs from what the registry's active bundle documents as the intended
    pin (e.g. a provider-side snapshot resolving differently for one request) — the entry
    always records what ACTUALLY happened, never re-derived from the registry after the
    fact. Almost always None; the simulation uses this exactly once, for the scripted
    model-boundary scenario."""
    thesis_caller = {"agent": "pe-thesis-tracker", "agent_version": "v1"}

    budget.consume("get_investment_thesis")
    tools_impl.get_investment_thesis(company_id, caller=thesis_caller)
    budget.consume("get_financials")
    financials = tools_impl.get_financials(company_id, quarter, caller=thesis_caller)
    budget.consume("get_trend_history")
    history = tools_impl.get_trend_history(company_id, limit=6, caller=thesis_caller)
    previous_entry = history[-1] if history else None

    ts_active = registry.get_active("trend-synthesizer")
    ts_version = ts_active["version"] if ts_active else "unknown"
    ts_model = model_override or (ts_active["model"] if ts_active else "unknown")

    errors: list[str] = []
    if pe_thesis_output is None:
        errors.append("pe-thesis-tracker produced no output")
    else:
        errors += [f"pe_thesis_output: {e}" for e in schema_validator.validate(pe_thesis_output, PE_THESIS_SCHEMA)]
    if trend_synth_output is None:
        errors.append("trend-synthesizer produced no output")
    else:
        errors += [f"trend_synth_output: {e}" for e in schema_validator.validate(trend_synth_output, TREND_SYNTH_SCHEMA)]

    if errors:
        entry = tools_impl.append_trend_entry({
            "company_id": company_id, "quarter": quarter, "relationship_type": "PE",
            "classifying_agent": "trend-synthesizer", "agent_version": ts_version, "model": ts_model,
            "metric_snapshot": financials, "classification": "assessment_failed",
            "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
        }, caller=thesis_caller)
        return {"entry": entry, "failed": True, "boundary_kind": None, "previous_entry": previous_entry}

    final_classification = _combine_pe_classification(pe_thesis_output["raw_classification"], trend_synth_output["read"])
    entry = tools_impl.append_trend_entry({
        "company_id": company_id, "quarter": quarter, "relationship_type": "PE",
        "classifying_agent": "trend-synthesizer", "agent_version": ts_version, "model": ts_model,
        "metric_snapshot": financials, "classification": final_classification,
        "rationale": (
            f"pe-thesis-tracker raw read: {pe_thesis_output['raw_classification']} "
            f"({pe_thesis_output['rationale']}) | trend-synthesizer: {trend_synth_output['read']} "
            f"({trend_synth_output['rationale']})"
        ),
        "contributing_assessments": [
            {"agent": "pe-thesis-tracker", "version": "v1",
             "raw_classification": pe_thesis_output["raw_classification"], "rationale": pe_thesis_output["rationale"]},
            {"agent": "trend-synthesizer", "version": ts_version, "model": ts_model,
             "read": trend_synth_output["read"], "rationale": trend_synth_output["rationale"]},
        ],
    }, caller=thesis_caller)

    boundary = model_boundary.detect_boundary(previous_entry, entry) if previous_entry else None

    newly_off_thesis = final_classification == "off_thesis" and (
        previous_entry is None or previous_entry["classification"] != "off_thesis"
    )
    if newly_off_thesis:
        notifications.dispatch_off_thesis_review(
            company_id=company_id, company_name=tools_impl.get_company_display_name(company_id),
            quarter=quarter, as_of_date=quarter_end_date(quarter), rationale=entry["rationale"],
        )

    return {"entry": entry, "failed": False, "boundary_kind": boundary, "previous_entry": previous_entry}


def quarter_end_date(quarter: str):
    from datetime import date
    year_str, q_str = quarter.split("-Q")
    month = int(q_str) * 3
    day = 31 if month in (3, 12) else 30
    return date(int(year_str), month, day)


def run_pd_company_cycle(
    *, company_id: str, quarter: str, covenant_field: str, thresholds: dict[str, float],
    pd_trajectory_output: dict[str, Any] | None, budget: CallBudget,
) -> dict[str, Any]:
    """One PD company's quarterly cycle. Classification is deterministic covenant math;
    pd_trajectory_output only supplies trajectory commentary for the rationale."""
    covenant_caller = {"agent": "pd-covenant-tracker", "agent_version": "v1"}

    budget.consume("get_loan_agreement")
    tools_impl.get_loan_agreement(company_id, caller=covenant_caller)
    budget.consume("get_financials")
    financials = tools_impl.get_financials(company_id, quarter, caller=covenant_caller)
    budget.consume("get_trend_history")
    history = tools_impl.get_trend_history(company_id, limit=6, caller=covenant_caller)
    previous_entry = history[-1] if history else None

    pd_active = registry.get_active("pd-covenant-tracker")
    pd_version = pd_active["version"] if pd_active else "unknown"
    pd_model = pd_active["model"] if pd_active else "unknown"

    errors: list[str] = []
    if pd_trajectory_output is None:
        errors.append("pd-covenant-tracker produced no output")
    else:
        errors += [f"pd_trajectory_output: {e}" for e in schema_validator.validate(pd_trajectory_output, PD_TRAJECTORY_SCHEMA)]

    if errors:
        entry = tools_impl.append_trend_entry({
            "company_id": company_id, "quarter": quarter, "relationship_type": "PD",
            "classifying_agent": "pd-covenant-tracker", "agent_version": pd_version, "model": pd_model,
            "metric_snapshot": financials, "classification": "assessment_failed",
            "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
        }, caller=covenant_caller)
        return {"entry": entry, "failed": True, "boundary_kind": None, "previous_entry": previous_entry}

    ratio = financials[covenant_field]
    classification = classify_pd_covenant(ratio, thresholds)
    entry = tools_impl.append_trend_entry({
        "company_id": company_id, "quarter": quarter, "relationship_type": "PD",
        "classifying_agent": "pd-covenant-tracker", "agent_version": pd_version, "model": pd_model,
        "metric_snapshot": financials, "classification": classification,
        "rationale": (
            f"{covenant_field}={ratio} vs warning>={thresholds['warning_at_or_above']}, "
            f"breach>={thresholds['breach_at_or_above']} -> {classification}. Trajectory "
            f"({pd_trajectory_output['trajectory']}): {pd_trajectory_output['rationale']}"
        ),
        "contributing_assessments": [
            {"agent": "pd-covenant-tracker", "version": pd_version, "model": pd_model,
             "trajectory": pd_trajectory_output["trajectory"], "rationale": pd_trajectory_output["rationale"]},
        ],
    }, caller=covenant_caller)

    boundary = model_boundary.detect_boundary(previous_entry, entry) if previous_entry else None
    return {"entry": entry, "failed": False, "boundary_kind": boundary, "previous_entry": previous_entry}


FLAGGED_CLASSIFICATIONS = {"off_thesis", "warning", "breach"}


def run_portfolio_quarter(
    *, quarter: str, as_of_date, portfolio_size: int, company_cycle_results: dict[str, dict[str, Any]],
    model_boundary_judgments: dict[str, dict[str, Any]] | None = None,
    systemic_spike_counterfactuals: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """After every company's per-company cycle for this quarter is done: cross-company risk
    assessment, incident creation, rollback, and notification dispatch. This is where
    systemic-flag-spike (inherently cross-company) and model-boundary routing actually fire.

    model_boundary_judgments: {company_id: model-boundary-interpreter output} for any company
    whose per-company cycle returned a non-None boundary_kind this quarter.
    systemic_spike_counterfactuals: {company_id: what the last-known-good version would have
    said on the identical input}, for at least one company affected by a systemic-flag-spike
    this quarter — attached directly to the incident's replay bundle at creation time.
    """
    model_boundary_judgments = model_boundary_judgments or {}
    systemic_spike_counterfactuals = systemic_spike_counterfactuals or {}

    flagged_company_ids = [
        cid for cid, result in company_cycle_results.items()
        if not result["failed"] and result["entry"]["classification"] in FLAGGED_CLASSIFICATIONS
    ]

    # Systemic-flag-spike is specifically the fingerprint of an AGENT-VERSION regression —
    # it must only count companies whose classification actually passed through the
    # versioned agent being tracked (trend-synthesizer, for PE). A PD covenant "warning" is
    # pure deterministic math (orchestrator.classify_pd_covenant) with no LLM anywhere in
    # its path, so it can never be evidence of an agent regression and must never be
    # co-mingled into this count — otherwise a genuine, unrelated PD covenant flag occurring
    # in the same quarter as one real PE flag could falsely trip the spike threshold. This
    # is exactly the false-positive the systemic-flag-spike rule exists to NOT produce.
    spike_candidate_ids = [
        cid for cid in flagged_company_ids
        if company_cycle_results[cid]["entry"]["classifying_agent"] == "trend-synthesizer"
    ]

    quarter_incidents: list[dict[str, Any]] = []
    quarter_notifications: list[dict[str, Any]] = []

    # --- systemic flag spike -> auto-rollback -----------------------------------------
    spike_finding = risk_scoring.check_systemic_flag_spike(spike_candidate_ids, portfolio_size)
    if spike_finding is not None:
        ts_active = registry.get_active("trend-synthesizer")
        incident = incidents.create_incident(
            kind=spike_finding.kind, company_ids=spike_candidate_ids,
            agent_version=ts_active["version"], model=ts_active["model"],
            input_snapshot={cid: company_cycle_results[cid]["entry"]["metric_snapshot"] for cid in spike_candidate_ids},
            output_snapshot={cid: company_cycle_results[cid]["entry"]["classification"] for cid in spike_candidate_ids},
            risk_tier=spike_finding.risk_tier, routing=spike_finding.routing,
            detected_at=as_of_date.isoformat(), remediation_detail=spike_finding.justification,
            counterfactual=systemic_spike_counterfactuals or None,
        )
        # soft_fix.py is the ONLY module permitted to perform the rollback action itself;
        # notifications.py only ever sends messages about what happened, never acts.
        rollback_pointer = soft_fix.auto_rollback_to_last_known_good("trend-synthesizer", reason=spike_finding.justification)
        incidents.record_human_review(
            incident["incident_id"], resolved_by="pulse-auto-rollback",
            human_note=f"Auto-rolled back trend-synthesizer to {rollback_pointer['active_version']}.",
            new_status="auto_resolved",
        )
        quarter_incidents.append(incident)
        quarter_notifications += notifications.dispatch_for_incident(incident)

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
        quarter_incidents.append(incident)
        quarter_notifications += notifications.dispatch_for_incident(incident)

    return {
        "quarter": quarter, "flagged_company_ids": flagged_company_ids,
        "incidents": quarter_incidents, "notifications": quarter_notifications,
    }


def check_credit_committee_escalation(company_id: str, quarter: str, as_of_date, trend_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic policy_rules check for the Credit Committee reporting clause. This is
    NOT a risk_scoring finding — it's a correctly-functioning escalation, not a system
    failure, so it dispatches directly rather than creating an incident. Returns the
    notification dispatch record if the clause is newly triggered, else None."""
    if not policy_rules.credit_committee_clause_triggered(trend_history):
        return None
    # Only dispatch once — the moment the streak first reaches the threshold, not every
    # subsequent quarter it stays at or above it (that would re-notify every quarter).
    streak = policy_rules.count_consecutive_warning_quarters(trend_history)
    if streak != policy_rules.CONSECUTIVE_WARNING_THRESHOLD_FOR_CREDIT_COMMITTEE:
        return None
    return notifications.dispatch_credit_committee_escalation(company_id=company_id, quarter=quarter, as_of_date=as_of_date)
