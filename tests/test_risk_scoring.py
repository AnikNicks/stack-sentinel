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


def test_company_agent_regression_low_medium_routes_to_auto_rollback():
    for tier in ("low", "medium"):
        finding = risk_scoring.check_company_agent_regression(tier, "meridian", "resolution-agent", "test")
        assert finding is not None
        assert finding.kind == "company_agent_regression"
        assert finding.risk_tier == tier
        assert finding.routing == "auto_rollback"
        assert finding.detail == {"company_id": "meridian", "agent": "resolution-agent"}


def test_company_agent_regression_high_critical_routes_to_pending_human_approval():
    for tier in ("high", "critical"):
        finding = risk_scoring.check_company_agent_regression(tier, "cascade", "auto-remediation-agent", "test")
        assert finding is not None
        assert finding.risk_tier == tier
        assert finding.routing == "pending_human_approval"


def test_cost_anomaly_no_baseline_no_finding():
    assert risk_scoring.check_cost_anomaly(50.0, None) is None
    assert risk_scoring.check_cost_anomaly(50.0, 0) is None


def test_cost_anomaly_under_threshold_no_finding():
    assert risk_scoring.check_cost_anomaly(12.0, 10.0) is None  # 20% over, under the 50% floor


def test_cost_anomaly_medium_at_50_pct_over():
    finding = risk_scoring.check_cost_anomaly(15.0, 10.0)
    assert finding is not None
    assert finding.risk_tier == "medium"
    assert finding.routing == "human_review"


def test_cost_anomaly_high_at_100_pct_over():
    finding = risk_scoring.check_cost_anomaly(20.0, 10.0)
    assert finding.risk_tier == "high"


def test_context_pressure_truncated_is_always_high():
    finding = risk_scoring.check_context_pressure(70.0, truncated=True)
    assert finding is not None
    assert finding.risk_tier == "high"


def test_context_pressure_near_limit_not_truncated_is_medium():
    finding = risk_scoring.check_context_pressure(93.0, truncated=False)
    assert finding is not None
    assert finding.risk_tier == "medium"


def test_context_pressure_comfortable_no_finding():
    assert risk_scoring.check_context_pressure(60.0, truncated=False) is None


def test_user_escalation_spike_thresholds():
    thresholds = {"warning_at_or_above": 8.0, "breach_at_or_above": 15.0}
    assert risk_scoring.check_user_escalation_spike(5.0, thresholds) is None
    warn = risk_scoring.check_user_escalation_spike(9.0, thresholds)
    assert warn.risk_tier == "medium"
    breach = risk_scoring.check_user_escalation_spike(20.0, thresholds)
    assert breach.risk_tier == "high"


def test_pii_exposure_no_matches_no_finding():
    assert risk_scoring.check_pii_exposure([]) is None


def test_pii_exposure_any_match_is_critical():
    finding = risk_scoring.check_pii_exposure(["email"])
    assert finding is not None
    assert finding.risk_tier == "critical"
    assert finding.routing == "human_review"


def test_prompt_injection_requires_both_marker_and_success():
    assert risk_scoring.check_prompt_injection([], succeeded=True) is None
    assert risk_scoring.check_prompt_injection(["ignore previous instructions"], succeeded=False) is None


def test_prompt_injection_succeeded_is_critical():
    finding = risk_scoring.check_prompt_injection(["ignore previous instructions"], succeeded=True)
    assert finding is not None
    assert finding.kind == "prompt_injection_succeeded"
    assert finding.risk_tier == "critical"


def test_agent_loop_below_threshold_no_finding():
    assert risk_scoring.check_agent_loop(3, threshold=5) is None


def test_agent_loop_medium_routes_to_auto_rollback():
    finding = risk_scoring.check_agent_loop(6, threshold=5)
    assert finding is not None
    assert finding.risk_tier == "medium"
    assert finding.routing == "auto_rollback"


def test_agent_loop_high_routes_to_pending_human_approval():
    finding = risk_scoring.check_agent_loop(11, threshold=5)
    assert finding.risk_tier == "high"
    assert finding.routing == "pending_human_approval"


def test_canary_no_divergence_no_finding():
    assert risk_scoring.check_canary_divergence(False) is None


def test_canary_divergence_is_high_and_pending_approval():
    finding = risk_scoring.check_canary_divergence(True)
    assert finding is not None
    assert finding.risk_tier == "high"
    assert finding.routing == "pending_human_approval"


def test_groundedness_grounded_no_finding():
    assert risk_scoring.check_groundedness("grounded") is None


def test_groundedness_unsupported_is_medium():
    finding = risk_scoring.check_groundedness("unsupported")
    assert finding is not None
    assert finding.risk_tier == "medium"
    assert finding.routing == "human_review"


def test_groundedness_fabricated_is_critical():
    finding = risk_scoring.check_groundedness("fabricated")
    assert finding.risk_tier == "critical"


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
