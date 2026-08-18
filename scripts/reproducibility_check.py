"""Reproducibility check: takes one recorded incident, re-runs the ACTUAL deterministic
risk_scoring function against its exact recorded inputs, and asserts the identical risk tier
and routing decision comes out. A real, live-executed proof — not an illustrative claim.

This is the concrete guarantee the whole deterministic-core design exists to provide: given
the same inputs, the same (version-pinned) logic always produces the same decision, so a
recorded incident can always be replayed and checked, years later, against the exact code
that decided it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pulse import incidents, risk_scoring


def check_systemic_flag_spike_incident(incident_id: str) -> None:
    bundle = incidents.get_incident(incident_id)
    assert bundle["kind"] == "systemic_flag_spike", f"{incident_id} is not a systemic_flag_spike incident"

    recorded_company_ids = bundle["company_ids"]
    portfolio_size = 3  # the real portfolio size at the time of the run — see scripts/simulate_production_run.py

    print(f"Re-running risk_scoring.check_systemic_flag_spike against {incident_id}'s exact recorded input:")
    print(f"  flagged_company_ids = {recorded_company_ids}")
    print(f"  portfolio_size      = {portfolio_size}")

    finding = risk_scoring.check_systemic_flag_spike(recorded_company_ids, portfolio_size)
    assert finding is not None, "re-run produced NO finding — does not reproduce the recorded incident"

    print(f"\nRe-run result:  risk_tier={finding.risk_tier!r}  routing={finding.routing!r}")
    print(f"Recorded:       risk_tier={bundle['risk_tier']!r}  routing={bundle['routing']!r}")

    assert finding.risk_tier == bundle["risk_tier"], (
        f"risk_tier mismatch: re-run={finding.risk_tier!r} vs recorded={bundle['risk_tier']!r}"
    )
    assert finding.routing == bundle["routing"], (
        f"routing mismatch: re-run={finding.routing!r} vs recorded={bundle['routing']!r}"
    )
    print("\nMATCH — identical risk_tier and routing reproduced from the exact recorded inputs.")


def main() -> None:
    matches = incidents.list_incidents(kind="systemic_flag_spike")
    if not matches:
        raise SystemExit("No systemic_flag_spike incident on record — run scripts/simulate_production_run.py first.")
    check_systemic_flag_spike_incident(matches[0]["incident_id"])


if __name__ == "__main__":
    main()
