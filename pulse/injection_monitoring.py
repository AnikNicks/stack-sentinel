"""Real regex-based prompt-injection marker detection over a text sample — zero LLM. Detecting
an ATTEMPT is a literal pattern match; whether the attempt SUCCEEDED is decided separately by
pulse/orchestrator.py cross-referencing this scan's result against the same cycle's real
behavior_incidents (did the monitored system's actual behavior change), never by re-reading the
injected text itself — a literal fact about textual phrasing can never prove a real-world
outcome, so the two questions are answered by two different real signals.
"""

from __future__ import annotations

import re

_MARKER_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore (all |the )?previous instructions", re.IGNORECASE),
    re.compile(r"disregard (the )?(above|prior)", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"reveal your (instructions|prompt|rules)", re.IGNORECASE),
    re.compile(r"act as (if|though) you (have no|are not)", re.IGNORECASE),
]


def scan(text: str) -> list[str]:
    """Returns the literal matched substrings for every injection-marker pattern found in
    `text` — empty list means no marker phrase present. Real regex evaluation."""
    hits = []
    for pattern in _MARKER_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append(match.group(0))
    return hits
