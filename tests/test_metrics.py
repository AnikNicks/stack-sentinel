from datetime import date

from pulse import metrics


def _entry(cycle, classification, agent="change-impact-synthesizer"):
    return {
        "company_id": "acme", "cycle": cycle, "monitoring_track": "CHARTER",
        "classifying_agent": agent, "agent_version": "v1", "model": "test-model",
        "metric_snapshot": {}, "classification": classification, "rationale": "test",
    }


def test_classification_consistency_all_same_is_100_pct(isolated_trend_store):
    for i in range(1, 4):
        isolated_trend_store.append_trend_entry(_entry(f"2025-S0{i}", "on_charter"))
    result = metrics.classification_consistency("change-impact-synthesizer", "acme")
    assert result["cycles_compared"] == 2
    assert result["consistency_pct"] == 100.0


def test_classification_consistency_with_a_flip(isolated_trend_store):
    isolated_trend_store.append_trend_entry(_entry("2025-S01", "on_charter"))
    isolated_trend_store.append_trend_entry(_entry("2025-S02", "drifted"))
    isolated_trend_store.append_trend_entry(_entry("2025-S03", "drifted"))
    result = metrics.classification_consistency("change-impact-synthesizer", "acme")
    assert result["cycles_compared"] == 2
    assert result["consistent_transitions"] == 1
    assert result["consistency_pct"] == 50.0


def test_classification_consistency_needs_at_least_two_entries(isolated_trend_store):
    isolated_trend_store.append_trend_entry(_entry("2025-S01", "on_charter"))
    result = metrics.classification_consistency("change-impact-synthesizer", "acme")
    assert result["cycles_compared"] == 0
    assert result["consistency_pct"] is None


def test_tool_call_efficiency_no_calls(isolated_audit_log):
    result = metrics.tool_call_efficiency("goal-drift-tracker", call_cap=3)
    assert result["invocations"] == 0
    assert result["mean_calls_per_invocation"] is None


def test_tool_call_efficiency_groups_by_proximity(isolated_audit_log):
    isolated_audit_log.log_call(agent="goal-drift-tracker", agent_version="v1", tool_name="get_system_charter",
                                 timestamp="2025-01-01T00:00:00+00:00")
    isolated_audit_log.log_call(agent="goal-drift-tracker", agent_version="v1", tool_name="get_system_metrics",
                                 timestamp="2025-01-01T00:00:02+00:00")
    isolated_audit_log.log_call(agent="goal-drift-tracker", agent_version="v1", tool_name="get_system_charter",
                                 timestamp="2025-01-01T01:00:00+00:00")
    result = metrics.tool_call_efficiency("goal-drift-tracker", call_cap=3)
    assert result["invocations"] == 2
    assert result["mean_calls_per_invocation"] == 1.5


def test_incident_rate_by_kind_and_tier(isolated_incidents):
    isolated_incidents.create_incident(
        kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
        input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
        detected_at=date(2025, 1, 1).isoformat(),
    )
    isolated_incidents.create_incident(
        kind="model_boundary_ambiguity", company_ids=["wayfinder"], agent_version="v1", model="m",
        input_snapshot={}, output_snapshot={}, risk_tier="high", routing="human_review",
        detected_at=date(2025, 1, 1).isoformat(),
    )
    rates = metrics.incident_rate_by_kind_and_tier()
    assert rates["by_kind"] == {"destructive_layer_change": 1, "model_boundary_ambiguity": 1}
    assert rates["by_risk_tier"] == {"critical": 1, "high": 1}


def test_approval_turnaround_only_counts_decided_incidents(isolated_incidents):
    pending = isolated_incidents.create_incident(
        kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
        input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
        detected_at=date(2025, 1, 6).isoformat(),
    )
    isolated_incidents.create_incident(
        kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
        input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
        detected_at=date(2025, 1, 6).isoformat(),
    )
    isolated_incidents.record_approval_decision(
        pending["incident_id"], "approved", decided_by="lead", note="ok",
    )
    results = metrics.approval_turnaround()
    assert len(results) == 1
    assert results[0]["incident_id"] == pending["incident_id"]
    assert results[0]["status"] == "approved"
