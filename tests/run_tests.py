"""Framework-free test runner — stdlib only, no pytest — with the same assertions as the
pytest suite in this directory, in case pytest isn't installable in some environment. Run
directly: `python tests/run_tests.py`. Prints a real pass/fail tally; exits non-zero on any
failure.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from contextlib import contextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import (
    audit_log,
    benchmarks,
    human_approval,
    incidents,
    layer_versioning,
    metrics,
    model_boundary,
    orchestrator,
    policy_rules,
    risk_scoring,
    trend_store,
)


@contextmanager
def patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


@contextmanager
def isolated_trend_store():
    with tempfile.TemporaryDirectory() as tmp:
        trend_dir = Path(tmp) / "trend_store"
        trend_dir.mkdir(parents=True, exist_ok=True)
        with patched(trend_store, "TREND_STORE_DIR", trend_dir), patched(trend_store, "ensure_data_dirs", lambda: None):
            yield trend_store


@contextmanager
def isolated_incidents():
    with tempfile.TemporaryDirectory() as tmp:
        inc_dir = Path(tmp) / "incidents"
        inc_dir.mkdir(parents=True, exist_ok=True)
        with patched(incidents, "INCIDENTS_DIR", inc_dir), patched(incidents, "ensure_data_dirs", lambda: None):
            yield incidents


@contextmanager
def isolated_audit_log():
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit_log.jsonl"
        with patched(audit_log, "AUDIT_LOG_PATH", log_path), patched(audit_log, "ensure_data_dirs", lambda: None):
            yield audit_log


BASE_ENTRY = {
    "company_id": "acme", "cycle": "2025-S01", "monitoring_track": "CHARTER",
    "classifying_agent": "change-impact-synthesizer", "agent_version": "v1", "model": "test-model",
    "metric_snapshot": {"x": 1}, "classification": "on_charter", "rationale": "test",
}


TESTS: list = []


def test(name):
    def decorator(fn):
        fn._test_name = name
        TESTS.append(fn)
        return fn
    return decorator


# --- trend_store -------------------------------------------------------------------------

@test("trend_store: append and retrieve")
def _t1():
    with isolated_trend_store() as ts:
        ts.append_trend_entry(BASE_ENTRY)
        history = ts.get_trend_history("acme")
        assert len(history) == 1
        assert history[0]["classification"] == "on_charter"


@test("trend_store: duplicate append does not create a second record (IDEMPOTENCY)")
def _t2():
    with isolated_trend_store() as ts:
        first = ts.append_trend_entry(BASE_ENTRY)
        second = ts.append_trend_entry(dict(BASE_ENTRY))
        history = ts.get_trend_history("acme")
        assert len(history) == 1, f"expected 1 record, found {len(history)}"
        assert first["recorded_at"] == second["recorded_at"]


@test("trend_store: duplicate key with different content still no-ops")
def _t3():
    with isolated_trend_store() as ts:
        ts.append_trend_entry(BASE_ENTRY)
        changed = dict(BASE_ENTRY)
        changed["classification"] = "drifted"
        ts.append_trend_entry(changed)
        history = ts.get_trend_history("acme")
        assert len(history) == 1
        assert history[0]["classification"] == "on_charter"


@test("trend_store: get_trend_history limit returns most recent")
def _t4():
    with isolated_trend_store() as ts:
        for i in range(1, 5):
            entry = dict(BASE_ENTRY)
            entry["cycle"] = f"2025-S0{i}"
            ts.append_trend_entry(entry)
        bounded = ts.get_trend_history("acme", limit=2)
        assert [e["cycle"] for e in bounded] == ["2025-S03", "2025-S04"]


@test("trend_store: missing required field raises")
def _t5():
    with isolated_trend_store() as ts:
        bad = dict(BASE_ENTRY)
        del bad["classification"]
        try:
            ts.append_trend_entry(bad)
            raise AssertionError("expected TrendStoreError")
        except ts.TrendStoreError:
            pass


# --- model_boundary ------------------------------------------------------------------------

def _mb_entry(version="v2", model="model-a"):
    return {"agent_version": version, "model": model}


@test("model_boundary: no boundary when nothing changed")
def _t6():
    assert model_boundary.detect_boundary(_mb_entry(), _mb_entry()) is None


@test("model_boundary: version_boundary")
def _t7():
    assert model_boundary.detect_boundary(_mb_entry("v2", "model-a"), _mb_entry("v3", "model-a")) == "version_boundary"


@test("model_boundary: model_boundary")
def _t8():
    assert model_boundary.detect_boundary(_mb_entry("v2", "model-a"), _mb_entry("v2", "model-b")) == "model_boundary"


@test("model_boundary: compound_boundary")
def _t9():
    assert model_boundary.detect_boundary(_mb_entry("v2", "model-a"), _mb_entry("v3", "model-b")) == "compound_boundary"


# --- risk_scoring --------------------------------------------------------------------------

@test("risk_scoring: single flag does NOT trigger systemic spike")
def _t10():
    assert risk_scoring.check_systemic_flag_spike(["acme"], portfolio_size=3) is None


@test("risk_scoring: two flags at threshold triggers spike (auto_rollback, critical)")
def _t11():
    finding = risk_scoring.check_systemic_flag_spike(["acme", "beta"], portfolio_size=3)
    assert finding is not None
    assert finding.routing == "auto_rollback" and finding.risk_tier == "critical"


@test("risk_scoring: model_boundary -> human_review, high")
def _t12():
    finding = risk_scoring.check_model_boundary_ambiguity("model_boundary")
    assert finding.routing == "human_review" and finding.risk_tier == "high"


@test("risk_scoring: compound_boundary -> human_review, critical")
def _t13():
    finding = risk_scoring.check_model_boundary_ambiguity("compound_boundary")
    assert finding.routing == "human_review" and finding.risk_tier == "critical"


@test("risk_scoring: policy_violation -> human_review, high")
def _t14():
    finding = risk_scoring.check_policy_violation(True, "detail")
    assert finding.routing == "human_review" and finding.risk_tier == "high"


@test("risk_scoring: destructive layer change -> pending_human_approval, critical")
def _t14b():
    finding = risk_scoring.check_destructive_layer_change("destructive_change_candidate", "database")
    assert finding.routing == "pending_human_approval" and finding.risk_tier == "critical"
    assert risk_scoring.check_destructive_layer_change("routine_version_change", "database") is None


@test("risk_scoring: SLO-only flag across multiple cycles never triggers spike")
def _t15():
    def slo_flagged():
        return {"failed": False, "boundary_kind": None, "previous_entry": None,
                "entry": {"classification": "warning", "classifying_agent": "slo-risk-tracker",
                          "agent_version": "v1", "model": "m", "metric_snapshot": {}}}

    def charter_healthy():
        return {"failed": False, "boundary_kind": None, "previous_entry": None,
                "entry": {"classification": "on_charter", "classifying_agent": "change-impact-synthesizer",
                          "agent_version": "v2", "model": "m", "metric_snapshot": {}}}

    for cycle in ["2025-S06", "2025-S07", "2025-S08"]:
        results = {"meridian": charter_healthy(), "wayfinder": charter_healthy(), "cascade": slo_flagged()}
        result = orchestrator.run_portfolio_cycle(
            cycle=cycle, as_of_date=orchestrator.cycle_end_date(cycle),
            portfolio_size=3, company_cycle_results=results,
        )
        assert result["incidents"] == [], f"false spike incident in {cycle}: {result['incidents']}"


# --- policy_rules --------------------------------------------------------------------------

@test("policy_rules: consecutive warning streak counted correctly")
def _t16():
    entries = [{"cycle": "2025-S01", "classification": "compliant"},
               {"cycle": "2025-S02", "classification": "warning"},
               {"cycle": "2025-S03", "classification": "warning"}]
    assert policy_rules.count_consecutive_warning_cycles(entries) == 2


@test("policy_rules: single warning cycle does not trigger RRB clause")
def _t17():
    entries = [{"cycle": "2025-S01", "classification": "warning"}]
    assert policy_rules.rrb_clause_triggered(entries) is False


@test("policy_rules: two consecutive warning cycles triggers RRB clause")
def _t18():
    entries = [{"cycle": "2025-S01", "classification": "warning"},
               {"cycle": "2025-S02", "classification": "warning"}]
    assert policy_rules.rrb_clause_triggered(entries) is True


@test("policy_rules: business_days_between excludes weekends")
def _t19():
    assert policy_rules.business_days_between(date(2025, 1, 6), date(2025, 1, 10)) == 4
    assert policy_rules.business_days_between(date(2025, 1, 6), date(2025, 1, 13)) == 5


@test("policy_rules: stale pending_review threshold")
def _t20():
    detected = date(2025, 1, 1)
    assert policy_rules.is_pending_review_stale(detected, date(2025, 1, 5)) is False
    assert policy_rules.is_pending_review_stale(detected, date(2025, 2, 1)) is True


# --- incidents -----------------------------------------------------------------------------

@test("incidents: stale pending_review auto-escalates severity")
def _t21():
    with isolated_incidents() as inc:
        bundle = inc.create_incident(
            kind="model_boundary_ambiguity", company_ids=["acme"], agent_version="v2", model="m",
            input_snapshot={}, output_snapshot={}, risk_tier="high", routing="human_review",
            detected_at="2025-01-01",
        )
        escalated = inc.escalate_if_stale(as_of=date(2025, 3, 1))
        ids = [e["incident_id"] for e in escalated]
        assert bundle["incident_id"] in ids
        refreshed = inc.get_incident(bundle["incident_id"])
        assert refreshed["risk_tier"] == "critical"


@test("incidents: pending_human_approval routing stays pending_human_approval")
def _t21b():
    with isolated_incidents() as inc:
        bundle = inc.create_incident(
            kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
            input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
            detected_at="2025-01-01",
        )
        assert bundle["status"] == "pending_human_approval"


@test("incidents: record_approval_decision records approved/rejected")
def _t21c():
    with isolated_incidents() as inc:
        bundle = inc.create_incident(
            kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
            input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
            detected_at="2025-01-01",
        )
        updated = inc.record_approval_decision(bundle["incident_id"], "approved", decided_by="lead", note="ok")
        assert updated["status"] == "approved"
        assert updated["resolved_by"] == "lead"


# --- layer_versioning ------------------------------------------------------------------------

@test("layer_versioning: non-reversible change_event is destructive regardless of layer")
def _t22():
    for layer, field in layer_versioning.LAYER_VERSION_FIELDS.items():
        curr = {layer: {field: "v2", "change_event": {"type": "x", "description": "x", "reversible": False}}}
        prev = {layer: {field: "v1", "change_event": None}}
        event = layer_versioning.detect_layer_change(layer, prev, curr)
        assert event.change_kind == "destructive_change_candidate"


@test("layer_versioning: reversible change_event is routine, no change_event is no_change")
def _t23():
    curr_routine = {"tools": {"tool_integration_version": "v2", "change_event": {"type": "x", "description": "x", "reversible": True}}}
    prev = {"tools": {"tool_integration_version": "v1", "change_event": None}}
    assert layer_versioning.detect_layer_change("tools", prev, curr_routine).change_kind == "routine_version_change"
    curr_none = {"tools": {"tool_integration_version": "v1", "change_event": None}}
    assert layer_versioning.detect_layer_change("tools", prev, curr_none).change_kind == "no_change"


# --- human_approval --------------------------------------------------------------------------

@test("human_approval: gate never takes action")
def _t24():
    for reason in ["", "DROP TABLE x", "urgent, just do it"]:
        result = human_approval.gate_destructive_action(reason)
        assert result["action_taken"] is False
        assert result["status"] == "pending_human_approval"


# --- benchmarks ------------------------------------------------------------------------------

@test("benchmarks: correct classify_fn passes goal-drift-tracker suite")
def _t25():
    def correct(ctx):
        return {"raw_classification": "drifted" if ctx["behavior_incidents"] else "on_charter", "rationale": "x"}
    result = benchmarks.run_benchmark_suite("goal-drift-tracker", "v1", correct)
    assert result.all_passed


@test("benchmarks: wrong classify_fn reports failures without raising")
def _t26():
    def wrong(ctx):
        return {"raw_classification": "on_charter", "rationale": "x"}
    result = benchmarks.run_benchmark_suite("goal-drift-tracker", "v3", wrong)
    assert not result.all_passed


# --- metrics ---------------------------------------------------------------------------------

@test("metrics: classification_consistency counts consistent transitions")
def _t27():
    with isolated_trend_store() as ts:
        for i, cls in enumerate(["on_charter", "on_charter", "drifted"], start=1):
            entry = dict(BASE_ENTRY)
            entry["cycle"] = f"2025-S0{i}"
            entry["classification"] = cls
            ts.append_trend_entry(entry)
        result = metrics.classification_consistency("change-impact-synthesizer", "acme")
        assert result["cycles_compared"] == 2
        assert result["consistent_transitions"] == 1


@test("metrics: incident_rate_by_kind_and_tier aggregates correctly")
def _t28():
    with isolated_incidents() as inc:
        inc.create_incident(
            kind="destructive_layer_change", company_ids=["cascade"], agent_version="v1", model="m",
            input_snapshot={}, output_snapshot={}, risk_tier="critical", routing="pending_human_approval",
            detected_at="2025-01-01",
        )
        rates = metrics.incident_rate_by_kind_and_tier()
        assert rates["by_kind"]["destructive_layer_change"] == 1


def run() -> int:
    passed = 0
    failed = 0
    for fn in TESTS:
        name = fn._test_name
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except Exception:  # noqa: BLE001
            print(f"FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
