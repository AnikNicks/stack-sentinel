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
    finding = risk_scoring.check_policy_violation(True, "missed Credit Committee report")
    assert finding is not None
    assert finding.routing == "human_review"
    assert finding.risk_tier == "high"


def test_no_policy_violation_no_finding():
    assert risk_scoring.check_policy_violation(False) is None


def test_assess_cycle_returns_all_firing_findings_together():
    findings = risk_scoring.assess_cycle(
        flagged_company_ids=["a", "b"], portfolio_size=3,
        boundary_kind="model_boundary", policy_violation_detected=True, policy_violation_detail="x",
    )
    kinds = sorted(f.kind for f in findings)
    assert kinds == ["model_boundary_ambiguity", "policy_violation", "systemic_flag_spike"]


def test_assess_cycle_quiet_when_nothing_fires():
    findings = risk_scoring.assess_cycle(flagged_company_ids=["a"], portfolio_size=3)
    assert findings == []


# --- The specific requirement: a single genuine PD covenant flag across multiple quarters
# must never trigger a false systemic-flag-spike incident, because PD classification is pure
# deterministic covenant math with no LLM agent version to regress. This is enforced by
# orchestrator.run_portfolio_quarter's classifying_agent filter, not by risk_scoring alone
# (risk_scoring just counts whatever list it's given) — so this test exercises the real
# orchestrator function end-to-end. ---

def test_pd_only_flag_across_multiple_quarters_never_triggers_spike():
    from pulse import orchestrator

    def pd_flagged_result():
        return {
            "failed": False, "boundary_kind": None, "previous_entry": None,
            "entry": {
                "classification": "warning", "classifying_agent": "pd-covenant-tracker",
                "agent_version": "v1", "model": "test-model", "metric_snapshot": {"total_net_leverage": 4.1},
            },
        }

    def pe_healthy_result(cid):
        return {
            "failed": False, "boundary_kind": None, "previous_entry": None,
            "entry": {
                "classification": "on_thesis", "classifying_agent": "trend-synthesizer",
                "agent_version": "v2", "model": "test-model", "metric_snapshot": {},
            },
        }

    for quarter in ["2026-Q2", "2026-Q3", "2026-Q4"]:
        company_cycle_results = {
            "northwind": pe_healthy_result("northwind"),
            "solace": pe_healthy_result("solace"),
            "ferrous_point": pd_flagged_result(),
        }
        result = orchestrator.run_portfolio_quarter(
            quarter=quarter, as_of_date=orchestrator.quarter_end_date(quarter), portfolio_size=3,
            company_cycle_results=company_cycle_results,
        )
        assert result["incidents"] == [], (
            f"a real, single-company PD covenant flag in {quarter} must never produce a "
            f"systemic_flag_spike incident, but got: {result['incidents']}"
        )
        assert result["flagged_company_ids"] == ["ferrous_point"]
