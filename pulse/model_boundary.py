"""Pure comparison between two consecutive trend-store entries for the same company.

This is the reproducibility mechanism the whole project exists to support: over a 3-5 year
hold the underlying LLM will change multiple times, and if a trend suddenly breaks, this
module is how you find out — from plain data, not from a model call — whether that's the
business changing or the model quietly changing interpretation underneath a "pinned" version.

No LLM involvement. Two dicts in, one label out.
"""

from __future__ import annotations

from typing import Any, Literal

BoundaryKind = Literal["version_boundary", "model_boundary", "compound_boundary"]


def detect_boundary(prev_entry: dict[str, Any], curr_entry: dict[str, Any]) -> BoundaryKind | None:
    """Compare consecutive entries' agent_version and model fields.

    - version_boundary: agent_version changed, model unchanged. Expected, reviewed drift —
      a new prompt/version was deliberately rolled out.
    - model_boundary: model changed, agent_version unchanged. The ambiguous case: the
      "pinned" version looks the same but its underlying interpretation may not be. Always
      routes to human review (risk_scoring.py) — never auto-resolved.
    - compound_boundary: both changed at once. A real deployment should NEVER let this
      happen — if both axes move in the same release, a broken trend afterward is
      unrootcauseable: you cannot tell whether the version change or the model change (or
      their interaction) is responsible. Change one axis at a time, always.
    - None: neither changed — no boundary, nothing to route.
    """
    version_changed = prev_entry.get("agent_version") != curr_entry.get("agent_version")
    model_changed = prev_entry.get("model") != curr_entry.get("model")

    if version_changed and model_changed:
        return "compound_boundary"
    if version_changed:
        return "version_boundary"
    if model_changed:
        return "model_boundary"
    return None


def find_boundary_in_history(entries: list[dict[str, Any]]) -> list[tuple[dict, dict, BoundaryKind]]:
    """Walk a company's trend history (oldest-first) and return every consecutive pair with
    a detected boundary, as (prev_entry, curr_entry, boundary_kind) triples."""
    found = []
    for prev_entry, curr_entry in zip(entries, entries[1:]):
        kind = detect_boundary(prev_entry, curr_entry)
        if kind is not None:
            found.append((prev_entry, curr_entry, kind))
    return found
