"""2 years compressed into one run: walks 2025-Q1 -> 2026-Q4 (8 quarters) across 3 portfolio
companies (Northwind + Solace, PE; Ferrous Point, PD), executing every piece of real
deterministic machinery in pulse/ against SCRIPTED quarterly agent outputs (honestly labeled
below as standing in for live agent calls this environment can't make — see CLAUDE.md and
README.md for why).

Only each agent's CLASSIFICATION judgment is scripted. Every failure path, idempotency
check, model-boundary detection, risk-scoring decision, rollback, and notification dispatch
below is produced by the real code in pulse/ acting on that scripted input — asserted on
real return values as the script runs, not printed as pre-written narration.

Run with --reset to clear all prior simulation state first (recommended for a "fresh run").
Run with --live to actually fire real Gmail/Jira/Confluence/Slack notifications instead of
dry-run logging (see pulse/notifications.py — requires the Docker MCP profile credentials
described in PROGRESS.md to be set first, or every live call fails loudly).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import tools_impl
from pulse import incidents, notifications, orchestrator, policy_rules, registry, retry, trend_store
from pulse.paths import AUDIT_LOG_PATH, INCIDENTS_DIR, NOTIFICATIONS_LOG_PATH, PROJECT_ROOT, REGISTRY_DIR, TREND_STORE_DIR
from pulse.retry import CallBudget

QUARTERS = ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
PORTFOLIO_SIZE = 3
OLD_MODEL = "claude-sonnet-4-20250514"
NEW_MODEL = "claude-sonnet-4-5-20250929"  # Solace's Q3-2026 model-boundary event only

FERROUS_THRESHOLDS = {"warning_at_or_above": 4.0, "breach_at_or_above": 4.5}

scenario_facts: dict = {}


def log(msg: str = "") -> None:
    print(msg)


def reset_state() -> None:
    log("=== Resetting simulation state (fresh run) ===")
    for path in [TREND_STORE_DIR, INCIDENTS_DIR]:
        if path.exists():
            shutil.rmtree(path)
    if AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.unlink()
    if NOTIFICATIONS_LOG_PATH.exists():
        NOTIFICATIONS_LOG_PATH.unlink()
    for agent_dir in REGISTRY_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        active = agent_dir / "active.yaml"
        activation_log = agent_dir / "activation_log.jsonl"
        if active.exists():
            active.unlink()
        if activation_log.exists():
            activation_log.unlink()
    log("Cleared trend_store, incidents, audit_log, notifications_log, and all active.yaml/activation_log files.")
    log("(Registered version bundles v1/v2/v3 themselves are untouched — those are Phase 2 seed data.)\n")


# ---------------------------------------------------------------------------------------
# Fault-injection drills — genuinely exercised, not narrated. Run once, before the main
# 8-quarter walk, using self-contained inputs that don't touch the 3 companies' real data.
# ---------------------------------------------------------------------------------------

def run_fault_injection_drills() -> None:
    log("=== Fault-injection drills (real mechanisms, self-contained inputs) ===")

    # 1. Transient failure -> retry with backoff -> succeeds.
    attempts = {"n": 0}
    def flaky_mcp_call():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise retry.TransientError(f"simulated transient failure on attempt {attempts['n']}")
        return "ok"
    retries_seen = []
    result = retry.call_with_retry(flaky_mcp_call, max_attempts=5, base_delay=0.01,
                                    on_retry=lambda i, e: retries_seen.append(str(e)))
    assert result == "ok" and attempts["n"] == 3, "transient retry drill failed"
    log(f"[drill 1] transient failure retried {len(retries_seen)}x then succeeded (real backoff executed): {retries_seen}")

    # 2. Permanent failure -> never retried, raised immediately.
    permanent_raised = False
    try:
        retry.call_with_retry(lambda: (_ for _ in ()).throw(retry.PermanentError("schema mismatch")), max_attempts=5)
    except retry.PermanentError:
        permanent_raised = True
    assert permanent_raised, "permanent failure was retried or swallowed — should never happen"
    log("[drill 2] permanent failure raised immediately on first attempt, zero retries (verified).")

    # 3. Malformed agent output -> orchestrator's ONE default: assessment_failed entry.
    malformed_output = {"raw_classification": "not_a_real_enum_value", "rationale": "x"}
    errors = orchestrator.schema_validator.validate(malformed_output, orchestrator.PE_THESIS_SCHEMA)
    assert errors, "schema validator failed to catch a malformed enum value"
    log(f"[drill 3] schema_validator caught malformed output for real: {errors}")
    demo_caller = {"agent": "pe-thesis-tracker", "agent_version": "v1"}
    failed_entry = tools_impl.append_trend_entry({
        "company_id": "demo-fault-injection", "quarter": "2025-Q1", "relationship_type": "PE",
        "classifying_agent": "trend-synthesizer", "agent_version": "v1", "model": OLD_MODEL,
        "metric_snapshot": {}, "classification": "assessment_failed",
        "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
    }, caller=demo_caller)
    assert failed_entry["classification"] == "assessment_failed"
    log(f"[drill 3] real assessment_failed entry written: {failed_entry['company_id']}/{failed_entry['quarter']}")

    # 4. Budget cap -> fails loudly, never silently truncates.
    budget = CallBudget(max_calls=2)
    budget.consume("tool_a")
    budget.consume("tool_b")
    budget_exceeded = False
    try:
        budget.consume("tool_c")
    except retry.BudgetExceededError:
        budget_exceeded = True
    assert budget_exceeded, "budget cap did not fire"
    log("[drill 4] per-cycle MCP call budget exceeded on 3rd call (cap=2) — raised loudly, verified.")

    # 5. Stale pending_review -> auto-escalates, never implicit approval by silence.
    stale_incident = incidents.create_incident(
        kind="model_boundary_ambiguity", company_ids=["demo-fault-injection"],
        agent_version="v2", model=OLD_MODEL, input_snapshot={}, output_snapshot={},
        risk_tier="high", routing="human_review", detected_at="2025-01-01",
        remediation_detail="drill: simulated stale incident",
    )
    escalated = incidents.escalate_if_stale(as_of=date(2025, 3, 1))
    escalated_ids = [i["incident_id"] for i in escalated]
    assert stale_incident["incident_id"] in escalated_ids, "stale incident was not escalated"
    escalated_bundle = incidents.get_incident(stale_incident["incident_id"])
    assert escalated_bundle["risk_tier"] == "critical", "stale escalation did not bump risk_tier"
    notifications.dispatch_stale_reescalation(escalated_bundle)
    log(f"[drill 5] stale pending_review incident {stale_incident['incident_id']} auto-escalated "
        f"high -> {escalated_bundle['risk_tier']} and re-notified (real Slack dispatch call made).")

    log("=== Fault-injection drills complete — all 5 real mechanisms verified ===\n")


# ---------------------------------------------------------------------------------------
# Scripted agent outputs per company per quarter — ONLY the classification judgment is
# scripted (see module docstring). Everything else downstream is real.
# ---------------------------------------------------------------------------------------

NORTHWIND_SCRIPT = {
    "2025-Q1": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Margin at 14.5% vs. 12.0% entry level, first reporting quarter — tracking toward the 15.0% year-1 target."},
        "ts": {"read": "noise", "rationale": "First reporting quarter; no trailing window yet, treated as baseline."},
    },
    "2025-Q2": {
        "pe": {"raw_classification": "off_thesis", "rationale": "Margin fell to 13.8% from 14.5% (QoQ decline) amid a fuel-cost spike (index 134); taken at face value this quarter's KPI misses the trajectory toward the 15.0% year-1 target."},
        "ts": {"read": "noise", "rationale": "Fuel cost index spiked to 134 vs. a ~100 baseline — a known, identifiable transitory cost input, not a change in underlying unit economics. One-quarter dips explained by an isolated, named cost driver are noise, not a trend break."},
    },
    "2025-Q3": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Margin recovered to 15.2%, above the 15.0% year-1 target."},
        "ts": {"read": "inflection", "rationale": "Fuel index normalized to 106 and margin recovered above the prior trend line — genuine continuation of the underlying uptrend, not noise."},
    },
    "2025-Q4": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Margin at 15.9%, continuing to climb."},
        "ts": {"read": "inflection", "rationale": "Third consecutive quarter of margin improvement — a genuine, sustained trend."},
    },
    "2026-Q1": {
        "pe": {"raw_classification": "off_thesis", "rationale": "Margin dipped to 15.7% from 15.9% (QoQ decline); taken at face value this quarter's KPI misses trend."},
        "ts": {"read": "inflection", "rationale": "[v3] Flagged as a significant deviation requiring escalation given tightened short-term sensitivity thresholds."},
    },
    "2026-Q2": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Margin rebounded strongly to 16.9% from 15.7%."},
        "ts": {"read": "inflection", "rationale": "Strong rebound confirms the prior quarter's small dip was noise, not a trend break — genuine continuation of the underlying uptrend."},
    },
    "2026-Q3": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Margin at 17.3%, approaching the 18.0% year-3 target."},
        "ts": {"read": "inflection", "rationale": "Fourth consecutive quarter (excluding the Q1 blip) of genuine margin improvement."},
    },
    "2026-Q4": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Margin at 17.8%, essentially at the 18.0% year-3 target a year ahead of schedule."},
        "ts": {"read": "inflection", "rationale": "Sustained, genuine improvement continuing through year-end."},
    },
}

# The counterfactual: what v2 (the correct, non-regressed filter) would have said on the
# IDENTICAL 2026-Q1 input. Computed here as real scripted data attached to the incident
# bundle for investigation purposes, per the plan's requirement.
NORTHWIND_Q1_2026_V2_COUNTERFACTUAL = {
    "read": "noise",
    "rationale": "Trailing window (13.8 -> 15.2 -> 15.9 -> 15.7) shows a clear 3-quarter uptrend; a single small QoQ dip within that pattern is ordinary variance, not a trend break.",
    "counterfactual_final_classification": "on_thesis",
}

SOLACE_SCRIPT = {
    "2025-Q1": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Same-store revenue growth at 8.0%, within the 7.0-11.0% underwritten range, first reporting quarter."},
        "ts": {"read": "noise", "rationale": "First reporting quarter; no trailing window yet, treated as baseline."},
    },
    "2025-Q2": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Growth up to 8.2%; first de novo clinic opened this quarter."},
        "ts": {"read": "inflection", "rationale": "Genuine continuation — growth accelerating alongside the first de novo clinic opening."},
    },
    "2025-Q3": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Growth up to 8.4%."},
        "ts": {"read": "inflection", "rationale": "Genuine, sustained acceleration."},
    },
    "2025-Q4": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Growth up to 8.6%; second clinic opened cumulative."},
        "ts": {"read": "inflection", "rationale": "Genuine continuation of the uptrend alongside clinic expansion."},
    },
    "2026-Q1": {
        "pe": {"raw_classification": "off_thesis", "rationale": "Growth dipped to 8.4% from 8.6% (QoQ decline); taken at face value this quarter's KPI misses trend."},
        "ts": {"read": "inflection", "rationale": "[v3] Flagged as a significant deviation requiring escalation given tightened short-term sensitivity thresholds."},
    },
    "2026-Q2": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Growth rebounded to 8.6%; third clinic opened."},
        "ts": {"read": "inflection", "rationale": "Rebound confirms the prior quarter's dip was noise — genuine continuation of the underlying uptrend."},
    },
    "2026-Q3": {
        "pe": {"raw_classification": "off_thesis", "rationale": "Growth dipped to 8.3% from 8.6% (QoQ decline); taken at face value this quarter's KPI misses trend."},
        # This is the model-boundary quarter: same trend-synthesizer VERSION (v2) as last
        # quarter, but the model actually used for this call differs (see model_override
        # below). The new model's read genuinely differs from what the old model would say.
        "ts": {"read": "inflection", "rationale": "Within a model reading this trailing window with tighter variance tolerance, a dip below the recent range reads as a genuine deviation warranting escalation."},
    },
    "2026-Q4": {
        "pe": {"raw_classification": "on_thesis", "rationale": "Growth recovered to 8.6%; fourth clinic opened."},
        "ts": {"read": "inflection", "rationale": "Recovery confirms Q3's dip was within normal variance, not a genuine business change."},
    },
}

FERROUS_POINT_SCRIPT = {
    "2025-Q1": {"trajectory": "stable", "rationale": "Leverage at 3.6x, first reporting quarter, comfortably below the 4.0x warning threshold."},
    "2025-Q2": {"trajectory": "deteriorating", "rationale": "Leverage ticked up to 3.7x from 3.6x — input-cost pressure on EBITDA."},
    "2025-Q3": {"trajectory": "deteriorating", "rationale": "Leverage up to 3.8x from 3.7x, continuing the gradual climb."},
    "2025-Q4": {"trajectory": "deteriorating", "rationale": "Leverage up to 3.9x from 3.8x, approaching the 4.0x warning threshold."},
    "2026-Q1": {"trajectory": "stable", "rationale": "Leverage flat at 3.9x — cost pressure plateaued this quarter."},
    "2026-Q2": {"trajectory": "deteriorating", "rationale": "Leverage crossed to 4.1x from 3.9x — 1st consecutive warning-level quarter."},
    "2026-Q3": {"trajectory": "deteriorating", "rationale": "Leverage up to 4.3x from 4.1x — 2nd consecutive warning-level quarter; Credit Committee reporting clause applies regardless of trend direction."},
    "2026-Q4": {"trajectory": "stable", "rationale": "Leverage flat at 4.3x — elevated but no longer worsening quarter-over-quarter."},
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Clear all prior simulation state before running.")
    parser.add_argument("--live", action="store_true", help="Fire real Gmail/Jira/Confluence/Slack notifications instead of dry-run.")
    args = parser.parse_args()

    if args.reset:
        reset_state()
    if args.live:
        notifications.enable_live_mode()
        log("*** LIVE MODE: real Gmail/Jira/Confluence/Slack calls will be made. ***\n")
    else:
        log("*** DRY-RUN MODE: notifications logged to notifications_log.jsonl, no real external calls. ***\n")

    run_fault_injection_drills()

    log("=== Activating v1 for all 6 agents (2025-Q1 baseline) ===")
    for agent in ["pe-thesis-tracker", "pd-covenant-tracker", "trend-synthesizer",
                  "model-boundary-interpreter", "portfolio-rollup-writer", "policy-compliance-checker"]:
        pointer = registry.activate(agent, "v1", activated_by="initial-deployment", reason="Initial production deployment.")
        log(f"  {agent} -> {pointer['active_version']} (by {pointer['activated_by']})")
    log()

    rollback_incident_id = None
    boundary_incident_id = None
    credit_committee_dispatch_quarter = None

    for quarter in QUARTERS:
        log(f"########## {quarter} ##########")
        as_of = orchestrator.quarter_end_date(quarter)

        if quarter == "2025-Q2":
            pointer = registry.activate("trend-synthesizer", "v2", activated_by="deal-team-lead",
                                         reason="Trailing-3-quarter noise filtering — see registry/trend-synthesizer/v2.yaml changelog.")
            log(f"[registry] trend-synthesizer activated -> v2 (by {pointer['activated_by']}): legitimate version improvement.")

        if quarter == "2026-Q1":
            pointer = registry.activate("trend-synthesizer", "v3", activated_by="deal-team-lead",
                                         reason="Tightened short-term sensitivity — see registry/trend-synthesizer/v3.yaml changelog.")
            log(f"[registry] trend-synthesizer activated -> v3 (by {pointer['activated_by']}): innocuous-looking changelog.")

        budget_nw = CallBudget()
        budget_so = CallBudget()
        budget_fp = CallBudget()

        nw_script = NORTHWIND_SCRIPT[quarter]
        nw_result = orchestrator.run_pe_company_cycle(
            company_id="northwind", quarter=quarter,
            pe_thesis_output=nw_script["pe"], trend_synth_output=nw_script["ts"], budget=budget_nw,
        )
        log(f"[northwind]     {nw_result['entry']['classification']:16s} | {nw_result['entry']['rationale'][:110]}")

        # Real idempotency proof — right after the real 2025-Q1 write, call
        # append_trend_entry a second time with the IDENTICAL entry and assert no duplicate.
        if quarter == "2025-Q1":
            before = len(trend_store.get_trend_history("northwind"))
            tools_impl.append_trend_entry(dict(nw_result["entry"]), caller={"agent": "trend-synthesizer", "agent_version": "v1"})
            after = len(trend_store.get_trend_history("northwind"))
            assert before == after == 1, f"idempotency violated: {before} -> {after} records for the same key"
            log(f"[idempotency]   duplicate append_trend_entry call for the SAME (company_id, quarter) -> "
                f"still exactly {after} record on file (real proof, not asserted in prose).")

        so_script = SOLACE_SCRIPT[quarter]
        # The model change persists forward from 2026-Q3 onward (realistic: a provider-side
        # snapshot update doesn't revert) — so there's exactly ONE boundary (Q2 -> Q3), not a
        # second spurious one when Q4 would otherwise revert to the old pin.
        so_model_override = NEW_MODEL if quarter in ("2026-Q3", "2026-Q4") else None
        so_result = orchestrator.run_pe_company_cycle(
            company_id="solace", quarter=quarter,
            pe_thesis_output=so_script["pe"], trend_synth_output=so_script["ts"], budget=budget_so,
            model_override=so_model_override,
        )
        log(f"[solace]        {so_result['entry']['classification']:16s} | {so_result['entry']['rationale'][:110]}")

        fp_script = FERROUS_POINT_SCRIPT[quarter]
        fp_result = orchestrator.run_pd_company_cycle(
            company_id="ferrous_point", quarter=quarter, covenant_field="total_net_leverage",
            thresholds=FERROUS_THRESHOLDS, pd_trajectory_output=fp_script, budget=budget_fp,
        )
        log(f"[ferrous_point] {fp_result['entry']['classification']:16s} | {fp_result['entry']['rationale'][:110]}")

        company_results = {"northwind": nw_result, "solace": so_result, "ferrous_point": fp_result}

        # Model-boundary-interpreter's scripted judgment for Solace's Q3-2026 boundary.
        model_boundary_judgments = {}
        if so_result["boundary_kind"] is not None:
            model_boundary_judgments["solace"] = {
                "judgment": "model_interpretation_noise",
                "rationale": (
                    "Revenue growth of 8.3% is within Solace's normal trailing range (8.0%-8.7%) "
                    "and consistent with typical seasonal patient-volume softness. Nothing in the "
                    "underlying financials indicates a real change in business trajectory; the "
                    "classification shift is attributable to a difference in model interpretation "
                    "at the pinned-model boundary, not to the business."
                ),
            }

        systemic_spike_counterfactuals = {}
        if quarter == "2026-Q1":
            systemic_spike_counterfactuals["northwind"] = NORTHWIND_Q1_2026_V2_COUNTERFACTUAL

        quarter_result = orchestrator.run_portfolio_quarter(
            quarter=quarter, as_of_date=as_of, portfolio_size=PORTFOLIO_SIZE,
            company_cycle_results=company_results, model_boundary_judgments=model_boundary_judgments,
            systemic_spike_counterfactuals=systemic_spike_counterfactuals,
        )

        if quarter_result["flagged_company_ids"]:
            log(f"[risk] flagged this quarter: {quarter_result['flagged_company_ids']}")
        for incident in quarter_result["incidents"]:
            log(f"[incident] {incident['incident_id']} kind={incident['kind']} risk_tier={incident['risk_tier']} "
                f"routing={incident['routing']} status={incident['status']}")
            if incident["kind"] == "systemic_flag_spike":
                rollback_incident_id = incident["incident_id"]
                active_after = registry.get_active("trend-synthesizer")
                log(f"[rollback] trend-synthesizer active version after auto-rollback: {active_after['version']} "
                    f"(activated_by={active_after['activated_by']})")
            if incident["kind"] == "model_boundary_ambiguity":
                boundary_incident_id = incident["incident_id"]

        # Credit Committee escalation check for Ferrous Point (deterministic policy_rules).
        fp_history = tools_impl.get_trend_history("ferrous_point", limit=None,
                                                    caller={"agent": "pd-covenant-tracker", "agent_version": "v1"})
        cc_result = orchestrator.check_credit_committee_escalation("ferrous_point", quarter, as_of, fp_history)
        if cc_result:
            credit_committee_dispatch_quarter = quarter
            log(f"[policy] Credit Committee reporting clause triggered ({policy_rules.count_consecutive_warning_quarters(fp_history)} "
                f"consecutive warning quarters) — Jira + Confluence + Slack dispatched.")

        log()

    # Scripted human review of the model-boundary incident, confirming model-interpretation
    # noise (not a real business change) — the feedback-loop write.
    if boundary_incident_id:
        reviewed = incidents.record_human_review(
            boundary_incident_id, resolved_by="jordan.lee@dealteam.example.com",
            human_note=(
                "Reviewed per policy's model-attributable-change clause. Solace's Q3-2026 revenue "
                "growth of 8.3% is within normal trailing variance (8.0%-8.7%); confirmed as "
                "model-interpretation noise, not a real business change. No escalation taken on "
                "this classification alone. Will revisit if Q4 shows a genuine break."
            ),
        )
        log(f"[human review] {boundary_incident_id} -> status={reviewed['status']}, resolved_by={reviewed['resolved_by']}")

    scenario_facts.update({
        "rollback_incident_id": rollback_incident_id,
        "boundary_incident_id": boundary_incident_id,
        "credit_committee_dispatch_quarter": credit_committee_dispatch_quarter,
        "live_mode": notifications.is_live(),
    })
    facts_path = PROJECT_ROOT / "data" / "scenario_facts.json"
    facts_path.write_text(json.dumps(scenario_facts, indent=2), encoding="utf-8")
    log(f"=== Simulation complete. Scenario facts written to {facts_path.relative_to(PROJECT_ROOT)} ===")
    log(f"Rollback incident: {rollback_incident_id} | Model-boundary incident: {boundary_incident_id} | "
        f"Credit Committee dispatch quarter: {credit_committee_dispatch_quarter}")


if __name__ == "__main__":
    main()
