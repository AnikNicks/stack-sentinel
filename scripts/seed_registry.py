"""One-time data-authoring script: registers every agent's version bundle(s) via the real
pulse.registry.register_new_version() (so its own field validation runs for real). Does NOT
activate anything — activation happens live during scripts/simulate_production_run.py, so
that active.yaml's history is a genuine record of the simulated timeline, not pre-baked.

Safe to re-run: skips any version that's already registered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import registry
from pulse.registry import RegistryError

PINNED_MODEL = "claude-sonnet-4-20250514"

BUNDLES: dict[str, list[dict]] = {
    "pe-thesis-tracker": [
        {
            "version": "v1",
            "agent": "pe-thesis-tracker",
            "created": "2024-11-01",
            "changelog": "Initial release: compares current-quarter KPIs against the "
                         "underwritten thesis case and classifies on_thesis / watch / "
                         "off_thesis.",
            "prompt_file": ".claude/agents/pe-thesis-tracker.md",
            "tool_scope": ["get_investment_thesis", "get_financials", "get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether a PE portfolio company is still tracking "
                                    "toward the thesis it was underwritten on at close.",
        },
    ],
    "pd-covenant-tracker": [
        {
            "version": "v1",
            "agent": "pd-covenant-tracker",
            "created": "2024-10-15",
            "changelog": "Initial release: wraps deterministic covenant math and judges "
                         "trajectory toward covenant thresholds, not just point-in-time "
                         "pass/fail.",
            "prompt_file": ".claude/agents/pd-covenant-tracker.md",
            "tool_scope": ["get_loan_agreement", "get_financials", "get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge a PD borrower's trajectory toward its loan "
                                    "covenants, using pre-computed deterministic ratios.",
        },
    ],
    "trend-synthesizer": [
        {
            "version": "v1",
            "agent": "trend-synthesizer",
            "created": "2024-11-01",
            "changelog": "Initial release: flags a quarter's KPI movement as a genuine "
                         "inflection if it deviates from the immediately prior quarter beyond "
                         "a fixed threshold.",
            "prompt_file": ".claude/agents/trend-synthesizer.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether this quarter's number is a genuine "
                                    "inflection or normal noise, in the context of prior "
                                    "quarters.",
        },
        {
            "version": "v2",
            "agent": "trend-synthesizer",
            "created": "2025-04-01",
            "changelog": "Compares each quarter's KPI against the trailing 3-quarter trend "
                         "instead of only the immediately prior quarter, before calling "
                         "something an inflection. Reduces false positives on short-lived, "
                         "single-quarter cost or revenue noise (e.g. a one-quarter input-cost "
                         "spike) that v1 misread as thesis-breaking.",
            "prompt_file": ".claude/agents/trend-synthesizer.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether this quarter's number is a genuine "
                                    "inflection or normal noise, in the context of prior "
                                    "quarters.",
        },
        {
            "version": "v3",
            "agent": "trend-synthesizer",
            "created": "2026-01-01",
            "changelog": "Tightened sensitivity to short-term margin/revenue deviations to "
                         "surface emerging issues earlier in the quarter they first appear.",
            "prompt_file": ".claude/agents/trend-synthesizer.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether this quarter's number is a genuine "
                                    "inflection or normal noise, in the context of prior "
                                    "quarters.",
        },
    ],
    "model-boundary-interpreter": [
        {
            "version": "v1",
            "agent": "model-boundary-interpreter",
            "created": "2024-11-01",
            "changelog": "Initial release: judges whether a classification shift at a "
                         "detected model boundary looks like the business or looks like the "
                         "model.",
            "prompt_file": ".claude/agents/model-boundary-interpreter.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Given exactly the two trend entries bracketing a "
                                    "detected model boundary, judge whether the classification "
                                    "shift reflects the business or the model.",
        },
    ],
    "portfolio-rollup-writer": [
        {
            "version": "v1",
            "agent": "portfolio-rollup-writer",
            "created": "2024-11-01",
            "changelog": "Initial release: synthesizes each company's latest status into one "
                         "portfolio-level report.",
            "prompt_file": ".claude/agents/portfolio-rollup-writer.md",
            "tool_scope": ["list_portfolio_companies", "get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Synthesize every company's current status into one "
                                    "report a deal partner reads.",
        },
    ],
    "policy-compliance-checker": [
        {
            "version": "v1",
            "agent": "policy-compliance-checker",
            "created": "2024-11-01",
            "changelog": "Initial release: checks a cycle's proposed routing against "
                         "vector-retrieved policy clauses, alongside the deterministic "
                         "policy_rules checks.",
            "prompt_file": ".claude/agents/policy-compliance-checker.md",
            "tool_scope": ["search_policy"],
            "model": PINNED_MODEL,
            "objective_statement": "Check the system's proposed routing decision against the "
                                    "monitoring & escalation policy corpus.",
        },
    ],
}


def main() -> None:
    total_registered = 0
    total_skipped = 0
    for agent, bundles in BUNDLES.items():
        for bundle in bundles:
            try:
                registry.register_new_version(agent, bundle)
                print(f"registered {agent} {bundle['version']}")
                total_registered += 1
            except RegistryError as exc:
                if "already registered" in str(exc):
                    print(f"skipped {agent} {bundle['version']} (already registered)")
                    total_skipped += 1
                else:
                    raise
    print(f"\n{total_registered} version bundle(s) registered, {total_skipped} skipped.")
    print("Nothing activated — activation happens live in simulate_production_run.py.")


if __name__ == "__main__":
    main()
