"""Covers pulse/orchestrator.py's real wiring of policy-compliance-checker into
run_portfolio_cycle: every incident created is also checked, per company, against that
company's own policy document AND the shared corpus (real search_company_policy / search_policy
calls, real schema validation) — and a non-compliant read creates a separate policy_violation
incident routed to human_review, never silently correcting the original routing decision."""

from pulse import orchestrator


def _wayfinder_boundary_result():
    return {
        "failed": False, "boundary_kind": "model_boundary", "previous_entry": None,
        "entry": {
            "classification": "drifted", "classifying_agent": "change-impact-synthesizer",
            "agent_version": "v2", "model": "test-model",
            "metric_snapshot": {}, "contributing_assessments": [],
        },
    }


def test_compliant_policy_check_creates_no_violation_incident(isolated_incidents, isolated_registry, isolated_notifications, isolated_audit_log):
    cycle = "2099-S01"
    result = orchestrator.run_portfolio_cycle(
        cycle=cycle, as_of_date=orchestrator.cycle_end_date(cycle), portfolio_size=3,
        company_cycle_results={"wayfinder": _wayfinder_boundary_result()},
        model_boundary_judgments={"wayfinder": {"judgment": "uncertain", "rationale": "x"}},
        policy_compliance_outputs={
            ("wayfinder", "model_boundary_ambiguity"): {
                "compliant": True, "matched_clause_titles": ["Model and version boundary handling"],
                "rationale": "Routed to human_review before any escalation decision, as required.",
            },
        },
    )
    kinds = [i["kind"] for i in result["incidents"]]
    assert kinds == ["model_boundary_ambiguity"], "a compliant check must never create a policy_violation incident"

    checked_incident = result["incidents"][0]
    assert checked_incident["policy_check"]["wayfinder"]["checked"] is True
    assert checked_incident["policy_check"]["wayfinder"]["compliant"] is True


def test_noncompliant_policy_check_creates_a_separate_policy_violation_incident(isolated_incidents, isolated_registry, isolated_notifications, isolated_audit_log):
    cycle = "2099-S02"
    result = orchestrator.run_portfolio_cycle(
        cycle=cycle, as_of_date=orchestrator.cycle_end_date(cycle), portfolio_size=3,
        company_cycle_results={"wayfinder": _wayfinder_boundary_result()},
        model_boundary_judgments={"wayfinder": {"judgment": "uncertain", "rationale": "x"}},
        policy_compliance_outputs={
            ("wayfinder", "model_boundary_ambiguity"): {
                "compliant": False, "matched_clause_titles": ["Model and version boundary handling"],
                "rationale": "This routing skipped explicit human confirmation before treating the "
                             "shift as escalation-worthy.",
            },
        },
    )
    kinds = [i["kind"] for i in result["incidents"]]
    assert kinds == ["model_boundary_ambiguity", "policy_violation"]

    source_incident, violation_incident = result["incidents"]
    assert violation_incident["routing"] == "human_review"
    assert violation_incident["status"] == "pending_review"
    assert violation_incident["company_ids"] == ["wayfinder"]
    assert violation_incident["input_snapshot"]["source_incident_id"] == source_incident["incident_id"]
    assert violation_incident["input_snapshot"]["source_kind"] == "model_boundary_ambiguity"

    # The original incident's own routing is untouched — a policy miss is surfaced, never
    # silently auto-corrected.
    assert source_incident["routing"] == "human_review"
    assert source_incident["policy_check"]["wayfinder"]["compliant"] is False


def test_missing_scripted_output_gets_the_one_default_never_silently_skipped(isolated_incidents, isolated_registry, isolated_notifications, isolated_audit_log):
    cycle = "2099-S03"
    result = orchestrator.run_portfolio_cycle(
        cycle=cycle, as_of_date=orchestrator.cycle_end_date(cycle), portfolio_size=3,
        company_cycle_results={"wayfinder": _wayfinder_boundary_result()},
        model_boundary_judgments={"wayfinder": {"judgment": "uncertain", "rationale": "x"}},
        policy_compliance_outputs={},
    )
    checked_incident = result["incidents"][0]
    check = checked_incident["policy_check"]["wayfinder"]
    assert check["checked"] is False
    assert check["compliant"] is None
    # A missing/uncheckable compliance read must never be misread as a violation.
    assert [i["kind"] for i in result["incidents"]] == ["model_boundary_ambiguity"]
