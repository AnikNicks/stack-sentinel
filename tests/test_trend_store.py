"""Covers the idempotency guarantee specifically, plus basic append/retrieve behavior."""

import pytest

BASE_ENTRY = {
    "company_id": "acme", "cycle": "2025-S01", "monitoring_track": "CHARTER",
    "classifying_agent": "change-impact-synthesizer", "agent_version": "v1", "model": "test-model",
    "metric_snapshot": {"x": 1}, "classification": "on_charter", "rationale": "test",
}


def test_append_and_retrieve(isolated_trend_store):
    isolated_trend_store.append_trend_entry(BASE_ENTRY)
    history = isolated_trend_store.get_trend_history("acme")
    assert len(history) == 1
    assert history[0]["classification"] == "on_charter"


def test_duplicate_append_does_not_create_a_second_record(isolated_trend_store):
    """The idempotency guarantee: append_trend_entry(entry) called twice with an IDENTICAL
    entry for the same (company_id, cycle) must result in exactly one record on file."""
    first = isolated_trend_store.append_trend_entry(BASE_ENTRY)
    second = isolated_trend_store.append_trend_entry(dict(BASE_ENTRY))  # identical content, fresh dict

    history = isolated_trend_store.get_trend_history("acme")
    assert len(history) == 1, f"expected exactly 1 record, found {len(history)}"
    assert first["recorded_at"] == second["recorded_at"], "second call should return the ORIGINAL entry, not a new one"


def test_duplicate_key_different_content_still_no_op(isolated_trend_store):
    """Idempotency is keyed by (company_id, cycle) only — even a differently-worded
    duplicate for the same key must not create a second record (the original stands)."""
    isolated_trend_store.append_trend_entry(BASE_ENTRY)
    changed = dict(BASE_ENTRY)
    changed["classification"] = "drifted"
    changed["rationale"] = "a completely different rationale"
    isolated_trend_store.append_trend_entry(changed)

    history = isolated_trend_store.get_trend_history("acme")
    assert len(history) == 1
    assert history[0]["classification"] == "on_charter", "original entry must be preserved, not overwritten"


def test_get_trend_history_limit_returns_most_recent(isolated_trend_store):
    for i in range(1, 5):
        entry = dict(BASE_ENTRY)
        entry["cycle"] = f"2025-S0{i}"
        isolated_trend_store.append_trend_entry(entry)

    full = isolated_trend_store.get_trend_history("acme")
    assert [e["cycle"] for e in full] == ["2025-S01", "2025-S02", "2025-S03", "2025-S04"]

    bounded = isolated_trend_store.get_trend_history("acme", limit=2)
    assert [e["cycle"] for e in bounded] == ["2025-S03", "2025-S04"], "limit must return the MOST RECENT entries"


def test_missing_required_field_raises(isolated_trend_store):
    bad_entry = dict(BASE_ENTRY)
    del bad_entry["classification"]
    with pytest.raises(isolated_trend_store.TrendStoreError):
        isolated_trend_store.append_trend_entry(bad_entry)


def test_unrelated_companies_are_isolated(isolated_trend_store):
    entry_a = dict(BASE_ENTRY)
    entry_b = dict(BASE_ENTRY)
    entry_b["company_id"] = "other-co"
    isolated_trend_store.append_trend_entry(entry_a)
    isolated_trend_store.append_trend_entry(entry_b)
    assert len(isolated_trend_store.get_trend_history("acme")) == 1
    assert len(isolated_trend_store.get_trend_history("other-co")) == 1
