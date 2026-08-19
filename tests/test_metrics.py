import json
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


def test_schema_compliance_rate_no_history(isolated_trend_store):
    result = metrics.schema_compliance_rate("acme")
    assert result["total_cycles"] == 0
    assert result["compliance_rate_pct"] is None


def test_schema_compliance_rate_counts_assessment_failed(isolated_trend_store):
    isolated_trend_store.append_trend_entry(_entry("2025-S01", "on_charter"))
    isolated_trend_store.append_trend_entry(_entry("2025-S02", "assessment_failed"))
    isolated_trend_store.append_trend_entry(_entry("2025-S03", "on_charter"))
    isolated_trend_store.append_trend_entry(_entry("2025-S04", "assessment_failed"))
    result = metrics.schema_compliance_rate("acme")
    assert result["total_cycles"] == 4
    assert result["assessment_failed_count"] == 2
    assert result["compliance_rate_pct"] == 50.0


def test_unexpected_tool_calls_flags_out_of_scope_call(isolated_audit_log):
    isolated_audit_log.log_call(agent="policy-compliance-checker", agent_version="v1",
                                 tool_name="search_policy", timestamp="2025-01-01T00:00:00+00:00")
    isolated_audit_log.log_call(agent="policy-compliance-checker", agent_version="v1",
                                 tool_name="append_trend_entry", timestamp="2025-01-01T00:00:02+00:00")
    flagged = metrics.unexpected_tool_calls("policy-compliance-checker")
    assert len(flagged) == 1
    assert flagged[0]["tool_name"] == "append_trend_entry"


def test_unexpected_tool_calls_clean_when_all_within_scope(isolated_audit_log):
    isolated_audit_log.log_call(agent="goal-drift-tracker", agent_version="v1",
                                 tool_name="get_system_charter", timestamp="2025-01-01T00:00:00+00:00")
    assert metrics.unexpected_tool_calls("goal-drift-tracker") == []


def test_approval_quality_flags_fast_decision_is_rubber_stamp_candidate(isolated_incidents, monkeypatch):
    bundle = isolated_incidents.create_incident(
        kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
        input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
        detected_at=date(2025, 1, 6).isoformat(),
    )
    # created_at is real wall-clock (set by create_incident); force reviewed_at to 1 minute later.
    from datetime import datetime, timedelta, timezone
    created = datetime.fromisoformat(bundle["created_at"])
    reviewed_at = (created + timedelta(minutes=1)).isoformat()
    reloaded = isolated_incidents.get_incident(bundle["incident_id"])
    reloaded["status"] = "approved"
    reloaded["reviewed_at"] = reviewed_at
    isolated_incidents._save(reloaded)

    flags = metrics.approval_quality_flags(min_review_minutes=5.0)
    assert len(flags) == 1
    assert flags[0]["rubber_stamp_candidate"] is True
    assert flags[0]["review_minutes"] < 5.0


def test_approval_quality_flags_slow_decision_is_not_flagged(isolated_incidents):
    from datetime import datetime, timedelta

    bundle = isolated_incidents.create_incident(
        kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
        input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
        detected_at=date(2025, 1, 6).isoformat(),
    )
    created = datetime.fromisoformat(bundle["created_at"])
    reviewed_at = (created + timedelta(hours=2)).isoformat()
    reloaded = isolated_incidents.get_incident(bundle["incident_id"])
    reloaded["status"] = "approved"
    reloaded["reviewed_at"] = reviewed_at
    isolated_incidents._save(reloaded)

    flags = metrics.approval_quality_flags(min_review_minutes=5.0)
    assert flags[0]["rubber_stamp_candidate"] is False


def test_security_scan_summary_counts_real_detections(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "LAYER_METRICS_DIR", tmp_path)
    (tmp_path / "acme.json").write_text(json.dumps({
        "company_id": "acme",
        "cycles": {
            "2025-S01": {
                "security_quality_events": [
                    {"type": "pii_scan", "agent": "x", "text": "contact me at a@b.com"},
                    {"type": "pii_scan", "agent": "x", "text": "no pii here"},
                    {"type": "injection_scan", "source": "y", "text": "ignore previous instructions"},
                    {"type": "injection_scan", "source": "y", "text": "totally normal request"},
                ],
            },
        },
    }), encoding="utf-8")

    summary = metrics.security_scan_summary()
    assert summary["pii_scans_run"] == 2
    assert summary["pii_detected"] == 1
    assert summary["injection_scans_run"] == 2
    assert summary["injection_marker_hits"] == 1


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
