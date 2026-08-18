"""Detects and classifies layer-level version changes in the monitored system — the primary
detection module for this project's actual subject matter: layer versions, deployment/change
events, and discrete behavior-boundary incidents, never a smoothed trend line.

Sibling to pulse/model_boundary.py, but answering a different question. model_boundary.py
compares Stack Sentinel's OWN agent_version/model fields — is our classifier drifting.
This module compares the MONITORED SYSTEM's own per-layer version pointers — did the
monitored system deploy a real change, and was it reversible. Conflating the two would blur
"is our classifier drifting" with "is the target system doing something risky," and this
project's identity depends on keeping them distinct.

Reversibility is read straight off the authored change_event's "reversible" flag — a literal,
provided fact about the change itself (a schema drop vs. a config bump), never a judgment
call. change_event.reversible is False maps unconditionally to destructive_change_candidate,
regardless of which layer fired it; no agent adjudicates this — see
pulse/risk_scoring.check_destructive_layer_change and pulse/human_approval.py for what
happens next.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LAYER_VERSION_FIELDS = {
    "repo_cicd": "commit_sha",
    "database": "schema_migration_version",
    "memory": "memory_schema_version",
    "tools": "tool_integration_version",
    "mcp": "mcp_config_version",
    "production_app": "deployed_build_version",
}

LayerChangeKind = Literal["no_change", "routine_version_change", "destructive_change_candidate"]


@dataclass
class LayerChangeEvent:
    layer: str
    change_kind: LayerChangeKind
    from_version: str | None
    to_version: str
    change_event: dict[str, Any] | None


def detect_layer_change(layer: str, prev_layers: dict[str, Any] | None,
                         curr_layers: dict[str, Any]) -> LayerChangeEvent | None:
    """Compare one layer's version pointer between two consecutive cycles' `layers` dicts
    (the `layers` field of a cycle's metric_snapshot). Returns None only if the layer is
    absent from curr_layers entirely; otherwise always returns a LayerChangeEvent, classified
    no_change / routine_version_change / destructive_change_candidate.

    prev_layers may be None (first-ever cycle for this company) — treated as "no prior
    version to compare," so the current version is reported at face value: no_change if
    there's no change_event this cycle, routine/destructive per the change_event otherwise.
    """
    if layer not in curr_layers:
        return None
    version_field = LAYER_VERSION_FIELDS[layer]
    curr_entry = curr_layers[layer]
    to_version = curr_entry.get(version_field)
    change_event = curr_entry.get("change_event")
    from_version = prev_layers.get(layer, {}).get(version_field) if prev_layers else None

    if change_event is None:
        return LayerChangeEvent(
            layer=layer, change_kind="no_change",
            from_version=from_version, to_version=to_version, change_event=None,
        )

    change_kind: LayerChangeKind = (
        "destructive_change_candidate" if change_event.get("reversible") is False
        else "routine_version_change"
    )
    return LayerChangeEvent(
        layer=layer, change_kind=change_kind,
        from_version=from_version, to_version=to_version, change_event=change_event,
    )


def find_layer_changes_in_history(
    layer: str, entries: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], LayerChangeEvent]]:
    """Walk a company's oldest-first trend_history entries, returning every consecutive pair
    (prev_entry, curr_entry, LayerChangeEvent) where this layer had a real change_event this
    cycle. no_change cycles are skipped — this is a record of what actually happened, not a
    cycle-by-cycle audit of every layer every cycle."""
    results: list[tuple[dict[str, Any], dict[str, Any], LayerChangeEvent]] = []
    prev_entry: dict[str, Any] | None = None
    for entry in entries:
        curr_layers = entry["metric_snapshot"]["layers"]
        prev_layers = prev_entry["metric_snapshot"]["layers"] if prev_entry else None
        event = detect_layer_change(layer, prev_layers, curr_layers)
        if event is not None and event.change_kind != "no_change":
            results.append((prev_entry, entry, event))
        prev_entry = entry
    return results
