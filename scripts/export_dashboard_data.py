"""Exports one consolidated JSON snapshot of the real post-simulation state — trend_store,
incidents, registry version history (incl. the auto-rollback event), audit_log summary, and
notifications_log — for the dashboard artifact to embed. This is the single source of truth
the dashboard reads from; no numbers are hand-typed into dashboard/dashboard.html.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import audit_log, incidents, registry, trend_store
from pulse.paths import NOTIFICATIONS_LOG_PATH, PROJECT_ROOT

COMPANIES = [
    {"company_id": "northwind", "name": "Northwind Logistics Group", "relationship_type": "PE"},
    {"company_id": "solace", "name": "Solace Behavioral Health", "relationship_type": "PE"},
    {"company_id": "ferrous_point", "name": "Ferrous Point Industrial Supply", "relationship_type": "PD"},
]

AGENTS = [
    "pe-thesis-tracker", "pd-covenant-tracker", "trend-synthesizer",
    "model-boundary-interpreter", "portfolio-rollup-writer", "policy-compliance-checker",
]


def read_notifications() -> list[dict]:
    if not NOTIFICATIONS_LOG_PATH.exists():
        return []
    with NOTIFICATIONS_LOG_PATH.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    snapshot = {
        "companies": [],
        "incidents": incidents.list_incidents(),
        "registry": {},
        "notifications": read_notifications(),
        "audit_log_summary": {"total_calls": len(audit_log.read_log())},
    }

    for company in COMPANIES:
        cid = company["company_id"]
        snapshot["companies"].append({
            **company,
            "trend_history": trend_store.get_trend_history(cid),
        })

    for agent in AGENTS:
        versions = registry.list_versions(agent)
        active = registry.get_active(agent)
        activation_log_path = Path(registry.__file__).resolve().parent.parent / "registry" / agent / "activation_log.jsonl"
        activation_history = []
        if activation_log_path.exists():
            with activation_log_path.open("r", encoding="utf-8") as f:
                activation_history = [json.loads(line) for line in f if line.strip()]
        snapshot["registry"][agent] = {
            "versions": versions,
            "active": active,
            "activation_history": activation_history,
        }

    out_path = PROJECT_ROOT / "dashboard" / "data_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    print(f"Wrote dashboard snapshot: {out_path} "
          f"({len(snapshot['companies'])} companies, {len(snapshot['incidents'])} incidents, "
          f"{len(snapshot['notifications'])} notifications)")


if __name__ == "__main__":
    main()
