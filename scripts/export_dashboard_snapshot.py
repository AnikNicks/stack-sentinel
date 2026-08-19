"""Exports a full read-only snapshot of the live operator console's data, for the static
'preview' build published to GitHub Pages (dashboard/web's api.js switches to reading this
JSON file instead of hitting dashboard/api when built with VITE_STATIC_MODE=true). Every
value here is produced by calling the exact same mcp_server/pulse functions dashboard/api's
endpoints call — this script has zero business logic of its own, same discipline as
dashboard/api/main.py.

Deliberately excludes anything write-capable or live-LLM-backed (POST /incidents/*/decision,
POST /ask): the static preview is a snapshot of one real simulation run, not a live app, so
dashboard/web's static-mode api.js shims those two calls to a clear "not available in this
preview" rejection instead of reading from this file.

Run after scripts/simulate_production_run.py so the snapshot reflects the current real
data: `python scripts/export_dashboard_snapshot.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import tools_impl
from pulse import company_registry, incidents, metrics, registry, vector_store
from pulse.paths import PROJECT_ROOT
from pulse.retry import PermanentError

_CALLER = {"agent": "dashboard-snapshot-export", "agent_version": "external"}

OUTPUT_PATH = PROJECT_ROOT / "dashboard" / "web" / "src" / "fixtures" / "dashboard_snapshot.json"

AGENTS = [
    "goal-drift-tracker",
    "slo-risk-tracker",
    "change-impact-synthesizer",
    "model-boundary-interpreter",
    "portfolio-rollup-writer",
    "policy-compliance-checker",
    "groundedness-checker",
]


def build_snapshot() -> dict:
    companies = tools_impl.list_portfolio_companies(caller=_CALLER)

    trends, charters, slos, agents_by_company, policies = {}, {}, {}, {}, {}
    for c in companies:
        company_id = c["company_id"]
        trends[company_id] = tools_impl.get_trend_history(company_id, caller=_CALLER)

        if c["monitoring_track"] == "CHARTER":
            try:
                charters[company_id] = tools_impl.get_system_charter(company_id, caller=_CALLER)
            except PermanentError:
                pass
        else:
            try:
                slos[company_id] = tools_impl.get_slo_agreement(company_id, caller=_CALLER)
            except PermanentError:
                pass

        agents_by_company[company_id] = [
            {
                "agent": agent,
                "active": company_registry.get_active(company_id, agent),
                "versions": company_registry.list_versions(company_id, agent),
            }
            for agent in company_registry.COMPANY_AGENTS.get(company_id, [])
        ]

        policy_path = vector_store.company_policy_path(company_id)
        if policy_path.exists():
            policies[company_id] = {"company_id": company_id, "markdown": policy_path.read_text(encoding="utf-8")}

    registry_by_agent = {
        agent: {"active": registry.get_active(agent), "versions": registry.list_versions(agent)}
        for agent in AGENTS
    }

    return {
        "companies": companies,
        "trends": trends,
        "charters": charters,
        "slos": slos,
        "agents": agents_by_company,
        "policies": policies,
        "incidents": incidents.list_incidents(),
        "registry": registry_by_agent,
        "metrics": metrics.system_health_summary(),
    }


def main() -> None:
    snapshot = build_snapshot()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"Wrote dashboard snapshot ({len(snapshot['companies'])} companies, "
          f"{len(snapshot['incidents'])} incidents) -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
