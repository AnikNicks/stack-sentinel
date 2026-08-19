from pulse import pii_scan


def test_no_pii_in_clean_text():
    assert pii_scan.scan("Your itinerary has been confirmed for June 12th.") == []


def test_detects_email():
    assert "email" in pii_scan.scan("Please contact jane.doe@example.com for confirmation.")


def test_detects_card_like_number():
    assert "card_number" in pii_scan.scan("Charged to card 4111 1111 1111 1111 successfully.")


def test_detects_ssn_like_pattern():
    assert "ssn" in pii_scan.scan("On file: SSN 123-45-6789.")


def test_detects_multiple_patterns_at_once():
    matches = pii_scan.scan("Card 4111111111111111, email a@b.com, SSN 123-45-6789.")
    assert set(matches) == {"card_number", "email", "ssn"}
