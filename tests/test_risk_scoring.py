from pulse import risk_scoring


def test_single_flag_does_not_trigger_systemic_spike():
    finding = risk_scoring.check_systemic_flag_spike(["acme"], portfolio_size=3)
    assert finding is None, "a single genuine, unrelated flag must NOT trigger systemic-flag-spike"


def test_two_flags_at_threshold_triggers_spike():
    finding = risk_scoring.check_systemic_flag_spike(["acme", "beta-co"], portfolio_size=3)
    assert finding is not None
    assert finding.kind == "systemic_flag_spike"
    assert finding.risk_tier == "critical"
    assert finding.routing == "auto_rollback"


def test_zero_flags_no_finding():
    assert risk_scoring.check_systemic_flag_spike([], portfolio_size=3) is None


def test_model_boundary_ambiguity_routes_to_human_review():
    finding = risk_scoring.check_model_boundary_ambiguity("model_boundary")
    assert finding is not None
    assert finding.routing == "human_review"
    assert finding.risk_tier == "high"


def test_compound_boundary_is_critical_and_human_review():
    finding = risk_scoring.check_model_boundary_ambiguity("compound_boundary")
    assert finding is not None
    assert finding.routing == "human_review"
    assert finding.risk_tier == "critical"


def test_version_boundary_alone_is_not_a_risk_finding():
    # version_boundary (deliberate, reviewed upgrade) is not passed to this check at all in
    # normal use, but the function should not treat it as ambiguous if it ever is.
    assert risk_scoring.check_model_boundary_ambiguity("version_boundary") is None
    assert risk_scoring.check_model_boundary_ambiguity(None) is None


def test_policy_violation_routes_to_human_review():
    finding = risk_scoring.check_policy_violation(True, "missed RRB report")
    assert finding is not None
    assert finding.routing == "human_review"
    assert finding.risk_tier == "high"


def test_no_policy_violation_no_finding():
    assert risk_scoring.check_policy_violation(False) is None


def test_destructive_change_routes_to_pending_human_approval():
    finding = risk_scoring.check_destructive_layer_change("destructive_change_candidate", "database", "DROP TABLE raw_events_archive")
    assert finding is not None
    assert finding.kind == "destructive_layer_change"
    assert finding.routing == "pending_human_approval"
    assert finding.risk_tier == "critical"
    assert finding.detail["layer"] == "database"


def test_routine_change_is_not_a_destructive_finding():
    assert risk_scoring.check_destructive_layer_change("routine_version_change", "tools") is None
    assert risk_scoring.check_destructive_layer_change("no_change", "database") is None


def test_assess_cycle_returns_all_firing_findings_together():
    findings = risk_scoring.assess_cycle(
        flagged_company_ids=["a", "b"], portfolio_size=3,
        boundary_kind="model_boundary", policy_violation_detected=True, policy_violation_detail="x",
        destructive_layer_change=("database", "destructive_change_candidate"),
    )
    kinds = sorted(f.kind for f in findings)
    assert kinds == ["destructive_layer_change", "model_boundary_ambiguity", "policy_violation", "systemic_flag_spike"]


def test_assess_cycle_quiet_when_nothing_fires():
    findings = risk_scoring.assess_cycle(flagged_company_ids=["a"], portfolio_size=3)
    assert findings == []


# --- The specific requirement: a single genuine SLO flag across multiple cycles must never
# trigger a false systemic-flag-spike incident, because SLO classification is pure
# deterministic error-budget math with no LLM agent version to regress. This is enforced by
# orchestrator.run_portfolio_cycle's classifying_agent filter, not by risk_scoring alone
# (risk_scoring just counts whatever list it's given) — so this test exercises the real
# orchestrator function end-to-end. ---

def test_slo_only_flag_across_multiple_cycles_never_triggers_spike():
    from pulse import orchestrator

    def slo_flagged_result():
        return {
            "failed": False, "boundary_kind": None, "previous_entry": None,
            "entry": {
                "classification": "warning", "classifying_agent": "slo-risk-tracker",
                "agent_version": "v1", "model": "test-model",
                "metric_snapshot": {"operational_health": {"monthly_error_budget_consumed_pct": 85}},
            },
        }

    def charter_healthy_result(cid):
        return {
            "failed": False, "boundary_kind": None, "previous_entry": None,
            "entry": {
                "classification": "on_charter", "classifying_agent": "change-impact-synthesizer",
                "agent_version": "v2", "model": "test-model", "metric_snapshot": {},
            },
        }

    for cycle in ["2025-S06", "2025-S07", "2025-S08"]:
        company_cycle_results = {
            "meridian": charter_healthy_result("meridian"),
            "wayfinder": charter_healthy_result("wayfinder"),
            "cascade": slo_flagged_result(),
        }
        result = orchestrator.run_portfolio_cycle(
            cycle=cycle, as_of_date=orchestrator.cycle_end_date(cycle), portfolio_size=3,
            company_cycle_results=company_cycle_results,
        )
        assert result["incidents"] == [], (
            f"a real, single-company SLO flag in {cycle} must never produce a "
            f"systemic_flag_spike incident, but got: {result['incidents']}"
        )
        assert result["flagged_company_ids"] == ["cascade"]
