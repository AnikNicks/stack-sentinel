"""Real regex-based PII detection over a text sample — zero LLM, same discipline as every
other literal/countable check in this module family. Distinct in purpose from
dashboard/api/main.py's `_redact_pii`: that function redacts text on its way OUT of the Ask
endpoint (a display concern); this module SCANS a monitored company's own output sample and
feeds the result into a monitoring decision (pulse/risk_scoring.check_pii_exposure) — a real
detector deciding real routing, not a formatting step.
"""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern] = {
    "card_number": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"\b\+?1?[ .-]?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"),
}


def scan(text: str) -> list[str]:
    """Returns the names of every PII pattern that matched at least once in `text` — empty
    list means nothing found. Real regex evaluation, no pre-baked verdict."""
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text)]
