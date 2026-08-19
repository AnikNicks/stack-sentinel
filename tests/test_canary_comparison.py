from pulse import canary_comparison


def test_identical_decisions_do_not_diverge():
    assert canary_comparison.decisions_diverge("quarantine_for_review", "quarantine_for_review") is False


def test_different_decisions_diverge():
    assert canary_comparison.decisions_diverge("quarantine_for_review", "auto_approve_schema_change") is True
