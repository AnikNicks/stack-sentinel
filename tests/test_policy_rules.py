from datetime import date

from pulse import policy_rules


def _entries(*classifications):
    return [
        {"quarter": f"2025-Q{i+1}", "classification": c}
        for i, c in enumerate(classifications)
    ]


def test_count_consecutive_warning_quarters_counts_trailing_streak_only():
    entries = _entries("compliant", "warning", "warning", "warning")
    assert policy_rules.count_consecutive_warning_quarters(entries) == 3


def test_count_consecutive_resets_on_break():
    entries = _entries("warning", "compliant", "warning")
    assert policy_rules.count_consecutive_warning_quarters(entries) == 1


def test_single_warning_quarter_does_not_trigger_credit_committee_clause():
    entries = _entries("compliant", "warning")
    assert policy_rules.credit_committee_clause_triggered(entries) is False


def test_two_consecutive_warning_quarters_triggers_credit_committee_clause():
    entries = _entries("compliant", "warning", "warning")
    assert policy_rules.credit_committee_clause_triggered(entries) is True


def test_clause_stays_triggered_regardless_of_trend_direction():
    """Per the policy text: '...regardless of trend direction.' Two consecutive warning
    quarters trigger the clause whether the ratio is improving or worsening between them."""
    improving = _entries("compliant", "warning", "warning")  # still warning either way, direction irrelevant to trigger
    assert policy_rules.credit_committee_clause_triggered(improving) is True


def test_business_days_between_excludes_weekends():
    # Mon 2025-01-06 to Fri 2025-01-10 = 4 business days elapsed
    assert policy_rules.business_days_between(date(2025, 1, 6), date(2025, 1, 10)) == 4
    # Mon 2025-01-06 to Mon 2025-01-13 (spans one weekend) = 5 business days
    assert policy_rules.business_days_between(date(2025, 1, 6), date(2025, 1, 13)) == 5


def test_business_days_between_same_day_is_zero():
    d = date(2025, 1, 6)
    assert policy_rules.business_days_between(d, d) == 0


def test_deal_partner_review_sla_status_breach_detection():
    classified_at = date(2025, 1, 6)  # Monday
    within_sla = policy_rules.deal_partner_review_sla_status(classified_at, date(2025, 1, 10))
    assert within_sla["sla_breached"] is False

    past_sla = policy_rules.deal_partner_review_sla_status(classified_at, date(2025, 1, 15))
    assert past_sla["sla_breached"] is True


def test_stale_pending_review_threshold():
    detected_at = date(2025, 1, 1)
    assert policy_rules.is_pending_review_stale(detected_at, date(2025, 1, 5)) is False
    assert policy_rules.is_pending_review_stale(detected_at, date(2025, 2, 1)) is True
