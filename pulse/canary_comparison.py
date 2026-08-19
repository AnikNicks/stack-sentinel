"""Real categorical decision-mismatch check — the deterministic detector behind
pulse/risk_scoring.check_canary_divergence. Given what a company agent's last known-good
version decided on an input, and what a candidate version decided on the SAME input, a literal
string inequality on the decision itself is the fact; no similarity scoring or judgment is
needed to know a version that would have quarantined a batch and a version that would have
auto-approved it disagree.
"""

from __future__ import annotations


def decisions_diverge(old_decision: str, new_decision: str) -> bool:
    return old_decision != new_decision
