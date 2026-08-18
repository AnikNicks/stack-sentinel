"""Registers version bundles for every MONITORED COMPANY's own internal agents — the actual
subject of this system, distinct from scripts/seed_registry.py (which registers Stack
Sentinel's own six classifiers). Mirrors that script's pattern exactly: register only, never
activate — activation happens live in scripts/simulate_production_run.py so the timeline is a
genuine record of the simulated run, not pre-baked.

Safe to re-run: skips any version already registered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import company_registry
from pulse.company_registry import COMPANY_AGENTS, CompanyRegistryError

# (company_id, agent) -> extra versions beyond v1, each with the changelog that will later be
# superseded by a real flagged company_agent_event in the simulation.
EXTRA_VERSIONS: dict[tuple[str, str], list[dict]] = {
    ("meridian", "intake-triage-agent"): [
        {
            "version": "v2",
            "changelog": "Retuned ticket-routing prompt to reduce misroutes on ambiguous "
                         "subject lines.",
        },
    ],
    ("cascade", "auto-remediation-agent"): [
        {
            "version": "v2",
            "changelog": "Widened auto-remediation scope to include malformed-batch handling, "
                         "reducing manual review load.",
        },
    ],
}


def main() -> None:
    total_registered = 0
    total_skipped = 0
    for company_id, agents in COMPANY_AGENTS.items():
        for agent in agents:
            versions = [{"version": "v1", "changelog": "Initial release."}]
            versions += EXTRA_VERSIONS.get((company_id, agent), [])
            for v in versions:
                bundle = {
                    "version": v["version"], "company_id": company_id, "agent": agent,
                    "created": "2025-01-06", "changelog": v["changelog"],
                }
                try:
                    company_registry.register_new_version(company_id, agent, bundle)
                    print(f"registered {company_id}/{agent} {v['version']}")
                    total_registered += 1
                except CompanyRegistryError as exc:
                    if "already registered" in str(exc):
                        print(f"skipped {company_id}/{agent} {v['version']} (already registered)")
                        total_skipped += 1
                    else:
                        raise
    print(f"\n{total_registered} version bundle(s) registered, {total_skipped} skipped.")
    print("Nothing activated — activation happens live in simulate_production_run.py.")


if __name__ == "__main__":
    main()
