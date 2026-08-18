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

from pulse import incidents, model_boundary, orchestrator, policy_rules, risk_scoring, trend_store


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


BASE_ENTRY = {
    "company_id": "acme", "quarter": "2025-Q1", "relationship_type": "PE",
    "classifying_agent": "trend-synthesizer", "agent_version": "v1", "model": "test-model",
    "metric_snapshot": {"x": 1}, "classification": "on_thesis", "rationale": "test",
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
        assert history[0]["classification"] == "on_thesis"


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
        changed["classification"] = "off_thesis"
        ts.append_trend_entry(changed)
        history = ts.get_trend_history("acme")
        assert len(history) == 1
        assert history[0]["classification"] == "on_thesis"


@test("trend_store: get_trend_history limit returns most recent")
def _t4():
    with isolated_trend_store() as ts:
        for i in range(1, 5):
            entry = dict(BASE_ENTRY)
            entry["quarter"] = f"2025-Q{i}"
            ts.append_trend_entry(entry)
        bounded = ts.get_trend_history("acme", limit=2)
        assert [e["quarter"] for e in bounded] == ["2025-Q3", "2025-Q4"]


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


@test("risk_scoring: PD-only flag across multiple quarters never triggers spike")
def _t15():
    def pd_flagged():
        return {"failed": False, "boundary_kind": None, "previous_entry": None,
                "entry": {"classification": "warning", "classifying_agent": "pd-covenant-tracker",
                          "agent_version": "v1", "model": "m", "metric_snapshot": {}}}

    def pe_healthy():
        return {"failed": False, "boundary_kind": None, "previous_entry": None,
                "entry": {"classification": "on_thesis", "classifying_agent": "trend-synthesizer",
                          "agent_version": "v2", "model": "m", "metric_snapshot": {}}}

    for quarter in ["2026-Q2", "2026-Q3", "2026-Q4"]:
        results = {"northwind": pe_healthy(), "solace": pe_healthy(), "ferrous_point": pd_flagged()}
        result = orchestrator.run_portfolio_quarter(
            quarter=quarter, as_of_date=orchestrator.quarter_end_date(quarter),
            portfolio_size=3, company_cycle_results=results,
        )
        assert result["incidents"] == [], f"false spike incident in {quarter}: {result['incidents']}"


# --- policy_rules --------------------------------------------------------------------------

@test("policy_rules: consecutive warning streak counted correctly")
def _t16():
    entries = [{"quarter": "2025-Q1", "classification": "compliant"},
               {"quarter": "2025-Q2", "classification": "warning"},
               {"quarter": "2025-Q3", "classification": "warning"}]
    assert policy_rules.count_consecutive_warning_quarters(entries) == 2


@test("policy_rules: single warning quarter does not trigger Credit Committee clause")
def _t17():
    entries = [{"quarter": "2025-Q1", "classification": "warning"}]
    assert policy_rules.credit_committee_clause_triggered(entries) is False


@test("policy_rules: two consecutive warning quarters triggers Credit Committee clause")
def _t18():
    entries = [{"quarter": "2025-Q1", "classification": "warning"},
               {"quarter": "2025-Q2", "classification": "warning"}]
    assert policy_rules.credit_committee_clause_triggered(entries) is True


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
