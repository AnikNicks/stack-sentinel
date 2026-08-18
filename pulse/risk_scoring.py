"""Deterministic risk scoring. Three rules, each one-sentence-justifiable, zero LLM.

These rules are what fills the role a "procedural memory" system might otherwise fill in an
agentic system: instead of a learned, opaque pattern store, the rules that decide when to
auto-rollback or force human review are encoded and inspectable right here (see MEMORY.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RiskTier = Literal["low", "medium", "high", "critical"]
Routing = Literal["auto_rollback", "human_review", "none"]

# Tuned for a small portfolio (3-5 companies): an absolute count, not a ratio against a
# near-zero baseline, so a single genuine, unrelated flag never trips it.
SYSTEMIC_SPIKE_THRESHOLD = 2


@dataclass
class RiskFinding:
    kind: Literal["systemic_flag_spike", "model_boundary_ambiguity", "policy_violation"]
    risk_tier: RiskTier
    routing: Routing
    justification: str
    detail: dict[str, Any] = field(default_factory=dict)


def check_systemic_flag_spike(
    flagged_company_ids: list[str], portfolio_size: int,
    threshold: int = SYSTEMIC_SPIKE_THRESHOLD,
) -> RiskFinding | None:
    """A sharp, portfolio-wide jump in flagged companies in one quarter is the deterministic
    fingerprint of an agent-version regression, distinct from real portfolio-wide trouble
    (which shows up gradually, company by company, quarter over quarter — not all at once).

    Always routes to automatic rollback: reverting to a previously-live version is safe
    regardless of confidence, since the old version was already in production and known-good.
    """
    if len(flagged_company_ids) >= threshold:
        return RiskFinding(
            kind="systemic_flag_spike",
            risk_tier="critical",
            routing="auto_rollback",
            justification=(
                f"{len(flagged_company_ids)} of {portfolio_size} companies flagged in one "
                f"quarter (threshold {threshold}) — real trouble is gradual, not simultaneous; "
                "this pattern is the fingerprint of an agent-version regression."
            ),
            detail={"flagged_company_ids": flagged_company_ids, "portfolio_size": portfolio_size},
        )
    return None


def check_model_boundary_ambiguity(boundary_kind: str | None) -> RiskFinding | None:
    """A model-boundary (or compound-boundary) event means a classification change cannot be
    confidently attributed to the business by code alone — per the policy clause requiring
    human confirmation before a model-attributable change is used as the sole basis for an
    escalation, this is unconditionally routed to human review, never auto-resolved.
    """
    if boundary_kind == "model_boundary":
        return RiskFinding(
            kind="model_boundary_ambiguity",
            risk_tier="high",
            routing="human_review",
            justification=(
                "Model string changed with agent_version unchanged — the classification "
                "shift may be model-interpretation noise, not a real business change, and "
                "code cannot tell the difference; policy requires human confirmation."
            ),
            detail={"boundary_kind": boundary_kind},
        )
    if boundary_kind == "compound_boundary":
        return RiskFinding(
            kind="model_boundary_ambiguity",
            risk_tier="critical",
            routing="human_review",
            justification=(
                "Both agent_version and model changed at once — root cause is structurally "
                "unrecoverable from data alone (see model_boundary.py); escalated to critical "
                "and routed to human review, and this deployment pattern should never recur."
            ),
            detail={"boundary_kind": boundary_kind},
        )
    return None


def check_policy_violation(violation_detected: bool, detail: str = "") -> RiskFinding | None:
    """A policy-compliance miss (e.g. a covenant warning uncounted toward the Credit
    Committee reporting clause) is inherently a human-judgment-required case, per the same
    guardrail discipline as the model-boundary rule — a policy miss doesn't get silently
    auto-corrected, it gets surfaced to a human.
    """
    if violation_detected:
        return RiskFinding(
            kind="policy_violation",
            risk_tier="high",
            routing="human_review",
            justification=f"Policy-compliance violation flagged: {detail}",
            detail={"description": detail},
        )
    return None


def assess_cycle(
    *, flagged_company_ids: list[str], portfolio_size: int,
    boundary_kind: str | None = None,
    policy_violation_detected: bool = False, policy_violation_detail: str = "",
) -> list[RiskFinding]:
    """Run all three checks for one quarterly cycle. Returns every finding that fired —
    zero, one, or more than one can fire in the same cycle."""
    findings = []
    for finding in (
        check_systemic_flag_spike(flagged_company_ids, portfolio_size),
        check_model_boundary_ambiguity(boundary_kind),
        check_policy_violation(policy_violation_detected, policy_violation_detail),
    ):
        if finding is not None:
            findings.append(finding)
    return findings
