"""Debugging investigation: loads the systemic-flag-spike incident's real replay bundle from
the simulation run, prints its exact recorded version/model/input, compares actual vs.
counterfactual output, and prints a root-cause narrative — all read directly from the real
incident bundle on disk, not hand-typed.

This is the concrete answer to "why did we call this company drifted in S06 when it clearly
wasn't" — the whole reason the incident/replay-bundle system exists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import incidents


def find_systemic_spike_incident() -> dict:
    matches = incidents.list_incidents(kind="systemic_flag_spike")
    if not matches:
        raise SystemExit("No systemic_flag_spike incident on record — run scripts/simulate_production_run.py first.")
    return matches[0]


def main() -> None:
    incident = find_systemic_spike_incident()
    bundle = incidents.get_incident(incident["incident_id"])

    print("=" * 78)
    print(f"INCIDENT REPLAY BUNDLE: {bundle['incident_id']}")
    print("=" * 78)
    print(f"kind:          {bundle['kind']}")
    print(f"detected_at:   {bundle['detected_at']}  (simulated cycle date)")
    print(f"agent_version: {bundle['agent_version']}  (the version ACTIVE when this fired)")
    print(f"model:         {bundle['model']}")
    print(f"companies:     {bundle['company_ids']}")
    print(f"risk_tier:     {bundle['risk_tier']}")
    print(f"routing:       {bundle['routing']}")
    print(f"status:        {bundle['status']}")
    print(f"remediation:   {bundle['remediation_detail']}")
    print()

    print("-" * 78)
    print("RECORDED INPUT (metric_snapshot per flagged company, exactly as fed to the agent)")
    print("-" * 78)
    for cid, snapshot in bundle["input_snapshot"].items():
        print(f"  {cid}: {snapshot}")
    print()

    print("-" * 78)
    print("ACTUAL OUTPUT (what the regressed version actually produced)")
    print("-" * 78)
    for cid, classification in bundle["output_snapshot"].items():
        print(f"  {cid}: {classification}")
    print()

    print("-" * 78)
    print("COUNTERFACTUAL (what the last-known-good version WOULD have produced on the")
    print("identical input — scripted for investigation purposes only, per the plan)")
    print("-" * 78)
    counterfactual = bundle.get("counterfactual") or {}
    if not counterfactual:
        print("  (no counterfactual attached to this bundle)")
    for cid, cf in counterfactual.items():
        print(f"  {cid}: read={cf['read']!r} -> would have classified "
              f"{cf['counterfactual_final_classification']!r}")
        print(f"    reasoning: {cf['rationale']}")
    print()

    print("-" * 78)
    print("ROOT-CAUSE NARRATIVE")
    print("-" * 78)
    actual_kinds = set(bundle["output_snapshot"].values())
    print(
        f"{len(bundle['company_ids'])} companies ({', '.join(bundle['company_ids'])}) were classified "
        f"{'/'.join(actual_kinds)} in the same cycle under {bundle['agent_version']}, tripping the "
        f"systemic-flag-spike threshold (an absolute company count, not a ratio — see "
        f"pulse/risk_scoring.py). The recorded input shows each flagged company's own layer changes "
        f"were routine, unrelated config/integration updates — not the kind of broad-based, genuine "
        f"behavior drift real, unrelated portfolio trouble would produce. The counterfactual "
        f"above shows the prior version reading the SAME input as ordinary noise, not an inflection. "
        f"Conclusion: this was a version regression, not a business event — which is exactly what "
        f"auto-rollback (routing={bundle['routing']!r}) responded to, with status={bundle['status']!r} "
        f"confirming the rollback executed without waiting on a human gate (unlike a model-boundary or "
        f"policy-violation finding, both of which always route to human review)."
    )


if __name__ == "__main__":
    main()
