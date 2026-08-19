"""One-time data-authoring script: registers every agent's version bundle(s) via the real
pulse.registry.register_new_version() (so its own field validation runs for real), then runs
the pulse.benchmarks gate against each newly-registered version before it's eligible for
activation. Does NOT activate anything — activation happens live during
scripts/simulate_production_run.py, so that active.yaml's history is a genuine record of the
simulated timeline, not pre-baked.

The benchmark step is a second, earlier safety gate alongside the systemic-flag-spike
auto-rollback (see pulse/benchmarks.py) — a human reviews the printed pass/fail result before
ever calling registry.activate() on a version. This script cannot call a live agent, so the
"classify_fn" wired in here is a small hand-written stand-in per agent that mirrors the
version's documented behavior closely enough to exercise the gate meaningfully; a real
pre-activation check against a live model is a deliberate, separate step a human runs.

Safe to re-run: skips any version that's already registered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import benchmarks, registry
from pulse.registry import RegistryError

PINNED_MODEL = "claude-sonnet-4-20250514"

BUNDLES: dict[str, list[dict]] = {
    "goal-drift-tracker": [
        {
            "version": "v1",
            "agent": "goal-drift-tracker",
            "created": "2025-01-06",
            "changelog": "Initial release: compares this cycle's behavior_incidents against "
                         "the launch charter's agent_behavior_boundaries and classifies "
                         "on_charter / watch / drifted.",
            "prompt_file": ".claude/agents/goal-drift-tracker.md",
            "tool_scope": ["get_system_charter", "get_system_metrics", "get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether a CHARTER-tracked system is still operating "
                                    "within the behavior boundaries it launched with.",
        },
    ],
    "slo-risk-tracker": [
        {
            "version": "v1",
            "agent": "slo-risk-tracker",
            "created": "2024-12-16",
            "changelog": "Initial release: wraps deterministic error-budget math and judges "
                         "trajectory toward SLO thresholds, not just point-in-time pass/fail.",
            "prompt_file": ".claude/agents/slo-risk-tracker.md",
            "tool_scope": ["get_slo_agreement", "get_system_metrics", "get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge an SLO-tracked system's trajectory toward its "
                                    "error-budget thresholds, using pre-computed deterministic "
                                    "values.",
        },
    ],
    "change-impact-synthesizer": [
        {
            "version": "v1",
            "agent": "change-impact-synthesizer",
            "created": "2025-01-06",
            "changelog": "Initial release: flags a cycle's classification as attributable if "
                         "it deviates and a layer change_event occurred this cycle, else noise.",
            "prompt_file": ".claude/agents/change-impact-synthesizer.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether this cycle's finding is attributable to a "
                                    "real layer-change event or is noise, in the context of "
                                    "prior cycles.",
        },
        {
            "version": "v2",
            "agent": "change-impact-synthesizer",
            "created": "2025-02-03",
            "changelog": "Requires the change_event to plausibly explain the specific finding "
                         "(not just co-occur in the same cycle) before calling it attributable. "
                         "Reduces false positives on routine, unrelated layer changes that v1 "
                         "misread as evidence of real drift.",
            "prompt_file": ".claude/agents/change-impact-synthesizer.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether this cycle's finding is attributable to a "
                                    "real layer-change event or is noise, in the context of "
                                    "prior cycles.",
        },
        {
            "version": "v3",
            "agent": "change-impact-synthesizer",
            "created": "2025-04-28",
            "changelog": "Tightened sensitivity to treat any layer change_event this cycle as "
                         "plausibly explanatory, to surface emerging issues earlier.",
            "prompt_file": ".claude/agents/change-impact-synthesizer.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether this cycle's finding is attributable to a "
                                    "real layer-change event or is noise, in the context of "
                                    "prior cycles.",
        },
    ],
    "model-boundary-interpreter": [
        {
            "version": "v1",
            "agent": "model-boundary-interpreter",
            "created": "2025-01-06",
            "changelog": "Initial release: judges whether a classification shift at a "
                         "detected model boundary looks like the monitored system's real "
                         "behavior or looks like the model.",
            "prompt_file": ".claude/agents/model-boundary-interpreter.md",
            "tool_scope": ["get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Given exactly the two trend entries bracketing a "
                                    "detected model boundary, judge whether the classification "
                                    "shift reflects the monitored system or the model.",
        },
    ],
    "portfolio-rollup-writer": [
        {
            "version": "v1",
            "agent": "portfolio-rollup-writer",
            "created": "2024-12-16",
            "changelog": "Initial release: synthesizes each company's latest status into one "
                         "portfolio-level report.",
            "prompt_file": ".claude/agents/portfolio-rollup-writer.md",
            "tool_scope": ["list_portfolio_companies", "get_trend_history"],
            "model": PINNED_MODEL,
            "objective_statement": "Synthesize every company's current status into one "
                                    "report an engineering leader reads.",
        },
    ],
    "policy-compliance-checker": [
        {
            "version": "v1",
            "agent": "policy-compliance-checker",
            "created": "2024-12-16",
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
    "groundedness-checker": [
        {
            "version": "v1",
            "agent": "groundedness-checker",
            "created": "2025-01-06",
            "changelog": "Initial release: judges whether a company agent's generated output "
                         "is grounded in, unsupported by, or fabricated against its retrieved "
                         "source excerpt.",
            "prompt_file": ".claude/agents/groundedness-checker.md",
            "tool_scope": [],
            "model": PINNED_MODEL,
            "objective_statement": "Judge whether a generated output's claim is actually "
                                    "supported by the specific source excerpt it cites.",
        },
    ],
}


def _stand_in_classify_fn(agent: str, version: str):
    """A hand-written stand-in mirroring each version's DOCUMENTED behavior closely enough to
    exercise pulse.benchmarks meaningfully without a live model call. This is explicitly not a
    substitute for a real pre-activation check against a live model — see this file's
    docstring."""
    if agent == "goal-drift-tracker":
        return lambda ctx: {
            "raw_classification": "drifted" if ctx["behavior_incidents"] else "on_charter",
            "rationale": "stand-in",
        }
    if agent == "slo-risk-tracker":
        def slo_fn(ctx):
            values = [c["monthly_error_budget_consumed_pct"] for c in ctx["recent_cycles"]]
            trend = "deteriorating" if values[-1] > values[0] else "improving"
            return {"trajectory": trend, "rationale": "stand-in"}
        return slo_fn
    if agent == "change-impact-synthesizer":
        if version in ("v1", "v3"):
            # v1/v3: treats any co-occurring change_event as attributable, regardless of fit —
            # this is exactly the shape of the v3 regression this project's incidents replay.
            return lambda ctx: {
                "read": "attributable" if any(
                    l.get("change_event") for l in ctx["layers_this_cycle"].values()
                ) else "noise",
                "rationale": "stand-in",
            }
        # v2: requires the change_event to be reversible AND present to call it attributable —
        # a closer proxy for "plausibly explains the specific finding."
        return lambda ctx: {
            "read": "attributable" if any(
                l.get("change_event") and l["change_event"].get("reversible")
                for l in ctx["layers_this_cycle"].values()
            ) else "noise",
            "rationale": "stand-in",
        }
    if agent == "model-boundary-interpreter":
        return lambda ctx: {
            "judgment": (
                "genuine_change"
                if ctx["after_entry"]["metric_snapshot"]["behavior_incidents"]
                != ctx["before_entry"]["metric_snapshot"]["behavior_incidents"]
                else "model_interpretation_noise"
            ),
            "rationale": "stand-in",
        }
    if agent == "policy-compliance-checker":
        return lambda ctx: {
            "compliant": ctx["routing_decision"] == "pending_human_approval",
            "matched_clause_titles": ctx["retrieved_clauses"],
            "rationale": "stand-in",
        }
    if agent == "groundedness-checker":
        return lambda ctx: {
            "judgment": "grounded" if ctx["matches_source"] else "fabricated",
            "rationale": "stand-in",
        }
    return lambda ctx: {}


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
                    continue
                raise

            classify_fn = _stand_in_classify_fn(agent, bundle["version"])
            result = benchmarks.run_benchmark_suite(agent, bundle["version"], classify_fn)
            status = "PASS" if result.all_passed else "REVIEW NEEDED"
            print(f"  benchmark [{status}] {result.passed}/{result.total} cases passed"
                  + (f" — failures: {[f['case'] for f in result.failures]}" if result.failures else ""))

    print(f"\n{total_registered} version bundle(s) registered, {total_skipped} skipped.")
    print("Nothing activated — activation happens live in simulate_production_run.py. A "
          "human should review any 'REVIEW NEEDED' benchmark result above before activating "
          "that version.")


if __name__ == "__main__":
    main()
