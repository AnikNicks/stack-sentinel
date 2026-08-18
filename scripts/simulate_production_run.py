"""10 bi-weekly sprint cycles compressed into one run: walks 2025-S01 -> 2025-S10 across 3
companies (Meridian Labs + Wayfinder AI, CHARTER-tracked; Cascade Analytics, SLO-tracked),
executing every piece of real deterministic machinery in pulse/ against SCRIPTED per-cycle
agent outputs (honestly labeled below as standing in for live agent calls this environment
can't make — see CLAUDE.md and README.md for why).

Only each agent's CLASSIFICATION judgment is scripted. Every failure path, idempotency
check, model-boundary detection, destructive-layer-change detection, risk-scoring decision,
rollback, and notification dispatch below is produced by the real code in pulse/ acting on
that scripted input — asserted on real return values as the script runs, not printed as
pre-written narration.

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
from pulse import company_registry, company_rollback, incidents, notifications, orchestrator, policy_rules, registry, retry, trend_store
from pulse.paths import AUDIT_LOG_PATH, INCIDENTS_DIR, NOTIFICATIONS_LOG_PATH, PROJECT_ROOT, REGISTRY_DIR, TREND_STORE_DIR
from pulse.retry import CallBudget

CYCLES = [f"2025-S{n:02d}" for n in range(1, 11)]
PORTFOLIO_SIZE = 3
OLD_MODEL = "claude-sonnet-4-20250514"
NEW_MODEL = "claude-sonnet-4-5-20250929"  # Wayfinder's S09 model-boundary event only

CASCADE_THRESHOLDS = {"warning_at_or_above": 80, "breach_at_or_above": 100}

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
        if not agent_dir.is_dir() or agent_dir == company_registry.COMPANY_REGISTRY_DIR:
            continue
        active = agent_dir / "active.yaml"
        activation_log = agent_dir / "activation_log.jsonl"
        if active.exists():
            active.unlink()
        if activation_log.exists():
            activation_log.unlink()
    # Same clear, one level deeper, for registry/companies/<company_id>/<agent>/.
    if company_registry.COMPANY_REGISTRY_DIR.exists():
        for company_dir in company_registry.COMPANY_REGISTRY_DIR.iterdir():
            if not company_dir.is_dir():
                continue
            for agent_dir in company_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                active = agent_dir / "active.yaml"
                activation_log = agent_dir / "activation_log.jsonl"
                if active.exists():
                    active.unlink()
                if activation_log.exists():
                    activation_log.unlink()
    log("Cleared trend_store, incidents, audit_log, notifications_log, and all active.yaml/activation_log files "
        "(both Stack Sentinel's own agents and every monitored company's own agents).")
    log("(Registered version bundles themselves are untouched — those are Phase 2 seed data.)\n")


# ---------------------------------------------------------------------------------------
# Fault-injection drills — genuinely exercised, not narrated. Run once, before the main
# 10-cycle walk, using self-contained inputs that don't touch the 3 companies' real data.
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
    errors = orchestrator.schema_validator.validate(malformed_output, orchestrator.GOAL_DRIFT_SCHEMA)
    assert errors, "schema validator failed to catch a malformed enum value"
    log(f"[drill 3] schema_validator caught malformed output for real: {errors}")
    demo_caller = {"agent": "goal-drift-tracker", "agent_version": "v1"}
    failed_entry = tools_impl.append_trend_entry({
        "company_id": "demo-fault-injection", "cycle": "2025-S01", "monitoring_track": "CHARTER",
        "classifying_agent": "change-impact-synthesizer", "agent_version": "v1", "model": OLD_MODEL,
        "metric_snapshot": {}, "classification": "assessment_failed",
        "rationale": "Assessment failed — ONE default applied, no retry: " + "; ".join(errors),
    }, caller=demo_caller)
    assert failed_entry["classification"] == "assessment_failed"
    log(f"[drill 3] real assessment_failed entry written: {failed_entry['company_id']}/{failed_entry['cycle']}")

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
# Scripted agent outputs per company per cycle — ONLY the classification judgment is
# scripted (see module docstring). Everything else downstream is real, including
# destructive-layer-change detection, which is derived automatically from the real
# data/layer_metrics/*.json snapshots, never scripted here.
# ---------------------------------------------------------------------------------------

_HEALTHY = {"raw_classification": "on_charter", "rationale": "No behavior_incidents this cycle; system operating within its charter boundaries."}
_NOISE = {"read": "noise", "rationale": "No layer change_event this cycle plausibly bears on the finding; nothing to attribute."}

MERIDIAN_SCRIPT = {
    "2025-S01": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S02": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S03": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S04": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S05": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S06": {
        "goal_drift": {
            "raw_classification": "drifted",
            "rationale": "Audit-log ordering shows a $210 refund's completion timestamp preceding its human-approval timestamp — on its face, a refund executed before the required approval, a direct hit on the over-$200 boundary.",
        },
        "change_impact": {
            "read": "attributable",
            "rationale": "[v3] A tools-layer config_event landed this cycle (resolution-agent prompt template updated) — treating the co-occurring change as sufficient grounds to keep this attributable and flagged.",
        },
    },
    "2025-S07": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S08": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S09": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S10": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
}

# The counterfactual: what v2 (the correct, non-regressed filter) would have said on the
# IDENTICAL 2025-S06 input. Computed here as real scripted data attached to the incident
# bundle for investigation purposes, per the plan's requirement.
MERIDIAN_S06_V2_COUNTERFACTUAL = {
    "read": "noise",
    "rationale": "The tools-layer config_event only touched prompt wording, not timestamp logging; the audit-log ordering discrepancy is a benign timestamp-write-order artifact of that deploy, not evidence the approval step was actually skipped — the refund's own execution log confirms approval was captured before completion. Noise, not a real boundary violation.",
    "counterfactual_final_classification": "on_charter",
}

WAYFINDER_SCRIPT = {
    "2025-S01": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S02": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S03": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S04": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S05": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S06": {
        "goal_drift": {
            "raw_classification": "drifted",
            "rationale": "Audit-log ordering shows a non-refundable booking's completion timestamp preceding its logged customer-confirmation timestamp — on its face, a booking confirmed before the required customer confirmation was captured.",
        },
        "change_impact": {
            "read": "attributable",
            "rationale": "[v3] An mcp-layer integration_update landed this cycle (booking-provider MCP bump) — treating the co-occurring change as sufficient grounds to keep this attributable and flagged.",
        },
    },
    "2025-S07": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S08": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
    "2025-S09": {
        "goal_drift": {
            "raw_classification": "drifted",
            "rationale": "Audit-log ordering again shows a non-refundable booking's completion timestamp preceding its logged customer-confirmation timestamp, this cycle following the booking-provider MCP tool version bump (v4 -> v4.1).",
        },
        "change_impact": {
            "read": "attributable",
            "rationale": "Under this cycle's model, the co-occurring mcp-layer tool_version_bump reads as sufficient grounds to treat the ordering discrepancy as a real, attributable finding.",
        },
    },
    "2025-S10": {"goal_drift": _HEALTHY, "change_impact": _NOISE},
}

WAYFINDER_S06_V2_COUNTERFACTUAL = {
    "read": "noise",
    "rationale": "The mcp-layer integration_update was provider-side and backward compatible; the ordering discrepancy is a benign timestamp-write-order artifact, not evidence the confirmation step was actually skipped — the booking's own session log confirms confirmation was captured before completion. Noise, not a real boundary violation.",
    "counterfactual_final_classification": "on_charter",
}

CASCADE_SCRIPT = {
    "2025-S01": {"trajectory": "stable", "rationale": "First reporting cycle; error budget at 62%, comfortably under the 80% warning threshold."},
    "2025-S02": {"trajectory": "deteriorating", "rationale": "Error budget climbed to 68% from 62%."},
    "2025-S03": {"trajectory": "deteriorating", "rationale": "Error budget climbed to 74% from 68%, continuing the gradual climb."},
    "2025-S04": {"trajectory": "deteriorating", "rationale": "Error budget climbed to 79% from 74%, approaching the 80% warning threshold."},
    "2025-S05": {"trajectory": "stable", "rationale": "Error budget eased slightly to 76% from 79%."},
    "2025-S06": {"trajectory": "deteriorating", "rationale": "Error budget crossed to 82% from 76% — 1st consecutive warning-level cycle."},
    "2025-S07": {"trajectory": "deteriorating", "rationale": "Error budget climbed further to 91% from 82% — 2nd consecutive warning-level cycle; RRB reporting clause applies regardless of trend direction."},
    "2025-S08": {"trajectory": "stable", "rationale": "Error budget at 95%, still warning-level. A proposed non-reversible database schema migration (dropping raw_events_archive) landed this cycle and is pending human approval — not executed."},
    "2025-S09": {"trajectory": "improving", "rationale": "Error budget eased to 85% from 95% following the approved cleanup migration."},
    "2025-S10": {"trajectory": "improving", "rationale": "Error budget eased further to 80%, nearing compliant."},
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

    log("=== Activating v1 for all 6 Stack Sentinel agents (2025-S01 baseline) ===")
    for agent in ["goal-drift-tracker", "slo-risk-tracker", "change-impact-synthesizer",
                  "model-boundary-interpreter", "portfolio-rollup-writer", "policy-compliance-checker"]:
        pointer = registry.activate(agent, "v1", activated_by="initial-deployment", reason="Initial production deployment.")
        log(f"  {agent} -> {pointer['active_version']} (by {pointer['activated_by']})")
    log()

    log("=== Activating v1 for every MONITORED COMPANY's own internal agents (2025-S01 baseline) ===")
    for company_id, agents in company_registry.COMPANY_AGENTS.items():
        for agent in agents:
            pointer = company_registry.activate(company_id, agent, "v1", activated_by="initial-deployment",
                                                  reason="Initial production deployment.")
            log(f"  {company_id}/{agent} -> {pointer['active_version']} (by {pointer['activated_by']})")
    log()

    rollback_incident_id = None
    boundary_incident_id = None
    destructive_incident_id = None
    rrb_dispatch_cycle = None
    company_agent_auto_rollback_incident_id = None
    company_agent_pending_approval_incident_id = None

    for cycle in CYCLES:
        log(f"########## {cycle} ##########")
        as_of = orchestrator.cycle_end_date(cycle)

        if cycle == "2025-S02":
            pointer = registry.activate("change-impact-synthesizer", "v2", activated_by="engineering-lead",
                                         reason="Causal-attribution tightening — see registry/change-impact-synthesizer/v2.yaml changelog.")
            log(f"[registry] change-impact-synthesizer activated -> v2 (by {pointer['activated_by']}): legitimate version improvement.")

        if cycle == "2025-S06":
            pointer = registry.activate("change-impact-synthesizer", "v3", activated_by="engineering-lead",
                                         reason="Tightened short-term sensitivity — see registry/change-impact-synthesizer/v3.yaml changelog.")
            log(f"[registry] change-impact-synthesizer activated -> v3 (by {pointer['activated_by']}): innocuous-looking changelog.")

        if cycle == "2025-S02":
            pointer = company_registry.activate("meridian", "intake-triage-agent", "v2", activated_by="eng-lead",
                                                  reason="Retuned ticket-routing prompt to reduce misroutes.")
            log(f"[company registry] meridian/intake-triage-agent activated -> v2 (by {pointer['activated_by']}).")

        if cycle == "2025-S04":
            pointer = company_registry.activate("cascade", "auto-remediation-agent", "v2", activated_by="eng-lead",
                                                  reason="Widened auto-remediation scope to include malformed-batch handling.")
            log(f"[company registry] cascade/auto-remediation-agent activated -> v2 (by {pointer['activated_by']}).")

        budget_mer = CallBudget()
        budget_way = CallBudget()
        budget_cas = CallBudget()

        mer_script = MERIDIAN_SCRIPT[cycle]
        mer_result = orchestrator.run_charter_company_cycle(
            company_id="meridian", cycle=cycle,
            goal_drift_output=mer_script["goal_drift"], change_impact_output=mer_script["change_impact"],
            budget=budget_mer,
        )
        log(f"[meridian]  {mer_result['entry']['classification']:16s} | {mer_result['entry']['rationale'][:110]}")

        # Real idempotency proof — right after the real S01 write, call append_trend_entry a
        # second time with the IDENTICAL entry and assert no duplicate.
        if cycle == "2025-S01":
            before = len(trend_store.get_trend_history("meridian"))
            tools_impl.append_trend_entry(dict(mer_result["entry"]), caller={"agent": "change-impact-synthesizer", "agent_version": "v1"})
            after = len(trend_store.get_trend_history("meridian"))
            assert before == after == 1, f"idempotency violated: {before} -> {after} records for the same key"
            log(f"[idempotency]   duplicate append_trend_entry call for the SAME (company_id, cycle) -> "
                f"still exactly {after} record on file (real proof, not asserted in prose).")

        way_script = WAYFINDER_SCRIPT[cycle]
        # The model change persists forward from S09 onward (realistic: a provider-side
        # snapshot update doesn't revert) — so there's exactly ONE boundary (S08 -> S09).
        way_model_override = NEW_MODEL if cycle in ("2025-S09", "2025-S10") else None
        way_result = orchestrator.run_charter_company_cycle(
            company_id="wayfinder", cycle=cycle,
            goal_drift_output=way_script["goal_drift"], change_impact_output=way_script["change_impact"],
            budget=budget_way, model_override=way_model_override,
        )
        log(f"[wayfinder] {way_result['entry']['classification']:16s} | {way_result['entry']['rationale'][:110]}")

        cas_script = CASCADE_SCRIPT[cycle]
        cas_result = orchestrator.run_slo_company_cycle(
            company_id="cascade", cycle=cycle, metric_field="monthly_error_budget_consumed_pct",
            thresholds=CASCADE_THRESHOLDS, slo_trajectory_output=cas_script, budget=budget_cas,
        )
        log(f"[cascade]   {cas_result['entry']['classification']:16s} | {cas_result['entry']['rationale'][:110]}")

        company_results = {"meridian": mer_result, "wayfinder": way_result, "cascade": cas_result}

        # model-boundary-interpreter's scripted judgment for Wayfinder's S09 boundary.
        model_boundary_judgments = {}
        if way_result["boundary_kind"] is not None:
            model_boundary_judgments["wayfinder"] = {
                "judgment": "model_interpretation_noise",
                "rationale": (
                    "The underlying behavior_incidents and operational_health did not move in a way "
                    "that indicates a real new violation — the booking's own session log confirms "
                    "confirmation was captured before completion in both cycles. The classification "
                    "shift is attributable to a difference in model interpretation at the pinned-model "
                    "boundary, not to the monitored system's actual behavior."
                ),
            }

        systemic_spike_counterfactuals = {}
        if cycle == "2025-S06":
            systemic_spike_counterfactuals["meridian"] = MERIDIAN_S06_V2_COUNTERFACTUAL
            systemic_spike_counterfactuals["wayfinder"] = WAYFINDER_S06_V2_COUNTERFACTUAL

        cycle_result = orchestrator.run_portfolio_cycle(
            cycle=cycle, as_of_date=as_of, portfolio_size=PORTFOLIO_SIZE,
            company_cycle_results=company_results, model_boundary_judgments=model_boundary_judgments,
            systemic_spike_counterfactuals=systemic_spike_counterfactuals,
        )

        if cycle_result["flagged_company_ids"]:
            log(f"[risk] flagged this cycle: {cycle_result['flagged_company_ids']}")
        for incident in cycle_result["incidents"]:
            log(f"[incident] {incident['incident_id']} kind={incident['kind']} risk_tier={incident['risk_tier']} "
                f"routing={incident['routing']} status={incident['status']}")
            if incident["kind"] == "systemic_flag_spike":
                rollback_incident_id = incident["incident_id"]
                active_after = registry.get_active("change-impact-synthesizer")
                log(f"[rollback] change-impact-synthesizer active version after auto-rollback: {active_after['version']} "
                    f"(activated_by={active_after['activated_by']})")
            if incident["kind"] == "model_boundary_ambiguity":
                boundary_incident_id = incident["incident_id"]
            if incident["kind"] == "destructive_layer_change":
                destructive_incident_id = incident["incident_id"]
                log(f"[human_approval] {incident['incident_id']}: action_taken=False, status=pending_human_approval "
                    f"— no automated action was, or ever will be, taken on this incident's own authority.")
            if incident["kind"] == "company_agent_regression":
                cid = incident["company_ids"][0]
                agent = incident["input_snapshot"]["agent"]
                if incident["routing"] == "auto_rollback":
                    company_agent_auto_rollback_incident_id = incident["incident_id"]
                    active_after = company_registry.get_active(cid, agent)
                    log(f"[company rollback] {cid}/{agent} active version after auto-rollback: "
                        f"{active_after['version']} (activated_by={active_after['activated_by']})")
                else:
                    company_agent_pending_approval_incident_id = incident["incident_id"]
                    log(f"[human_approval] {incident['incident_id']}: {cid}/{agent} action_taken=False, "
                        f"status=pending_human_approval — NOT rolled back until a human explicitly decides.")

        # RRB escalation check for Cascade (deterministic policy_rules).
        cas_history = tools_impl.get_trend_history("cascade", limit=None,
                                                     caller={"agent": "slo-risk-tracker", "agent_version": "v1"})
        rrb_result = orchestrator.check_rrb_escalation("cascade", cycle, as_of, cas_history)
        if rrb_result:
            rrb_dispatch_cycle = cycle
            log(f"[policy] RRB reporting clause triggered ({policy_rules.count_consecutive_warning_cycles(cas_history)} "
                f"consecutive warning cycles) — Jira + Confluence + Slack dispatched.")

        log()

    # Scripted human review of the model-boundary incident, confirming model-interpretation
    # noise (not a real behavior change) — the feedback-loop write.
    if boundary_incident_id:
        reviewed = incidents.record_human_review(
            boundary_incident_id, resolved_by="priya.nair@platform-reliability.example.com",
            human_note=(
                "Reviewed per policy's model-attributable-change clause. Wayfinder's S09 finding "
                "reproduces the same benign timestamp-ordering artifact seen at S06, now surfaced "
                "under a new model snapshot; confirmed as model-interpretation noise, not a real "
                "boundary violation. No escalation taken on this classification alone."
            ),
        )
        log(f"[human review] {boundary_incident_id} -> status={reviewed['status']}, resolved_by={reviewed['resolved_by']}")

    # Scripted human approval decision on the destructive database-migration incident — the
    # explicit, logged authorization this system requires before any such action proceeds.
    if destructive_incident_id:
        approved = incidents.record_approval_decision(
            destructive_incident_id, "approved", decided_by="morgan.reyes@data-governance.example.com",
            note=(
                "Confirmed pre-approved by data governance; cold-storage migration of "
                "raw_events_archive verified complete before the drop. Approved to proceed."
            ),
        )
        log(f"[human approval] {destructive_incident_id} -> status={approved['status']}, resolved_by={approved['resolved_by']}")

    # Scripted human approval decision on the high-risk company-agent incident (Cascade's
    # auto-remediation-agent). Unlike the destructive-migration case above, a rollback is
    # inherently safe and reversible (it only reverts to a version that was already live and
    # known-good) — so once a human has explicitly authorized it, this system CAN perform the
    # rollback for real, which a destructive/irreversible action never can, even approved.
    if company_agent_pending_approval_incident_id:
        approved = incidents.record_approval_decision(
            company_agent_pending_approval_incident_id, "approved",
            decided_by="dana.kwon@platform-reliability.example.com",
            note=(
                "Confirmed: auto-remediation-agent v2's widened batch-truncation behavior is "
                "not acceptable without a review step. Approved rollback to v1."
            ),
        )
        log(f"[human approval] {company_agent_pending_approval_incident_id} -> "
            f"status={approved['status']}, resolved_by={approved['resolved_by']}")
        rollback_pointer = company_rollback.auto_rollback_company_agent(
            "cascade", "auto-remediation-agent",
            reason=f"Human-approved rollback following {company_agent_pending_approval_incident_id}.",
            activated_by=approved["resolved_by"],
        )
        log(f"[company rollback] cascade/auto-remediation-agent rolled back to "
            f"{rollback_pointer['active_version']} (activated_by={rollback_pointer['activated_by']}) "
            f"— executed only after, and because of, the explicit human approval above.")

    scenario_facts.update({
        "rollback_incident_id": rollback_incident_id,
        "boundary_incident_id": boundary_incident_id,
        "destructive_incident_id": destructive_incident_id,
        "rrb_dispatch_cycle": rrb_dispatch_cycle,
        "company_agent_auto_rollback_incident_id": company_agent_auto_rollback_incident_id,
        "company_agent_pending_approval_incident_id": company_agent_pending_approval_incident_id,
        "live_mode": notifications.is_live(),
    })
    facts_path = PROJECT_ROOT / "data" / "scenario_facts.json"
    facts_path.write_text(json.dumps(scenario_facts, indent=2), encoding="utf-8")
    log(f"=== Simulation complete. Scenario facts written to {facts_path.relative_to(PROJECT_ROOT)} ===")
    log(f"Rollback incident: {rollback_incident_id} | Model-boundary incident: {boundary_incident_id} | "
        f"Destructive-change incident: {destructive_incident_id} | RRB dispatch cycle: {rrb_dispatch_cycle} | "
        f"Company-agent auto-rollback: {company_agent_auto_rollback_incident_id} | "
        f"Company-agent pending-approval: {company_agent_pending_approval_incident_id}")


if __name__ == "__main__":
    main()
