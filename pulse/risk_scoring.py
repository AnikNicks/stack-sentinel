"""Deterministic risk scoring. Four rules, each one-sentence-justifiable, zero LLM.

These rules are what fills the role a "procedural memory" system might otherwise fill in an
agentic system: instead of a learned, opaque pattern store, the rules that decide when to
auto-rollback or force human review are encoded and inspectable right here (see MEMORY.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RiskTier = Literal["low", "medium", "high", "critical"]
Routing = Literal["auto_rollback", "human_review", "pending_human_approval", "none"]

# Tuned for a small portfolio (3-5 companies): an absolute count, not a ratio against a
# near-zero baseline, so a single genuine, unrelated flag never trips it.
SYSTEMIC_SPIKE_THRESHOLD = 2


@dataclass
class RiskFinding:
    kind: Literal["systemic_flag_spike", "model_boundary_ambiguity", "policy_violation",
                   "destructive_layer_change", "company_agent_regression"]
    risk_tier: RiskTier
    routing: Routing
    justification: str
    detail: dict[str, Any] = field(default_factory=dict)


def check_systemic_flag_spike(
    flagged_company_ids: list[str], portfolio_size: int,
    threshold: int = SYSTEMIC_SPIKE_THRESHOLD,
) -> RiskFinding | None:
    """A sharp, portfolio-wide jump in flagged companies in one cycle is the deterministic
    fingerprint of an agent-version regression, distinct from real portfolio-wide trouble
    (which shows up gradually, company by company, cycle over cycle — not all at once).

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
                f"cycle (threshold {threshold}) — real trouble is gradual, not simultaneous; "
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
    """A policy-compliance miss (e.g. an SLO warning uncounted toward the Reliability Review
    Board reporting clause) is inherently a human-judgment-required case, per the same
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


def check_destructive_layer_change(
    change_kind: str, layer: str, detail: str = "",
) -> RiskFinding | None:
    """A layer-level change_event assessed as non-reversible (data-loss potential, a schema
    drop without a verified rollback path, credential rotation without a fallback, etc.) must
    never be auto-remediated. This fires unconditionally on
    change_kind == "destructive_change_candidate", regardless of which layer — reversibility
    is a literal, provided fact (layer_versioning.detect_layer_change already computed it),
    not a judgment call, so no agent adjudicates this; it always routes to
    pending_human_approval and pulse/human_approval.py is the only thing ever called next.
    """
    if change_kind == "destructive_change_candidate":
        return RiskFinding(
            kind="destructive_layer_change",
            risk_tier="critical",
            routing="pending_human_approval",
            justification=(
                f"Non-reversible change_event on the '{layer}' layer — per policy, any "
                "irreversible layer change must be routed to a human for an explicit, logged "
                "decision before any downstream action proceeds; it is never auto-executed."
                + (f" {detail}" if detail else "")
            ),
            detail={"layer": layer, "change_kind": change_kind},
        )
    return None


def check_company_agent_regression(
    risk_tier: RiskTier, company_id: str, agent: str, detail: str = "",
) -> RiskFinding | None:
    """The risk-tiered response to a flagged event on a MONITORED COMPANY's own internal
    agent (e.g. Meridian's resolution-agent, Cascade's auto-remediation-agent) — the actual
    subject of this system, distinct from check_model_boundary_ambiguity (which defends
    Stack Sentinel's OWN classifiers).

    low/medium risk: routed to auto_rollback — pulse/company_rollback.py reverts the agent
    to its last known-good version with no human in the loop, the same reasoning as
    check_systemic_flag_spike's auto-rollback (the prior version was already live and
    known-good).
    high/critical risk: routed to pending_human_approval — pulse/human_approval.py's gate is
    called instead, and the agent is NOT rolled back until a human explicitly authorizes it
    via pulse.incidents.record_approval_decision. This mirrors
    check_destructive_layer_change's contract exactly: a high-risk company-agent action is
    never auto-executed, full stop.
    """
    if risk_tier in ("low", "medium"):
        return RiskFinding(
            kind="company_agent_regression",
            risk_tier=risk_tier,
            routing="auto_rollback",
            justification=(
                f"{agent} ({company_id}) flagged {risk_tier}-risk — reverting to its last "
                f"known-good version automatically, no human gate required. {detail}"
            ),
            detail={"company_id": company_id, "agent": agent},
        )
    if risk_tier in ("high", "critical"):
        return RiskFinding(
            kind="company_agent_regression",
            risk_tier=risk_tier,
            routing="pending_human_approval",
            justification=(
                f"{agent} ({company_id}) flagged {risk_tier}-risk — a rollback this severe is "
                f"never auto-executed; routed for an explicit, logged human decision. {detail}"
            ),
            detail={"company_id": company_id, "agent": agent},
        )
    return None


def assess_cycle(
    *, flagged_company_ids: list[str], portfolio_size: int,
    boundary_kind: str | None = None,
    policy_violation_detected: bool = False, policy_violation_detail: str = "",
    destructive_layer_change: tuple[str, str] | None = None,
) -> list[RiskFinding]:
    """Run all four checks for one sprint cycle. Returns every finding that fired — zero,
    one, or more than one can fire in the same cycle. destructive_layer_change, if given, is
    (layer, change_kind) for one layer's change_event this cycle."""
    findings = []
    for finding in (
        check_systemic_flag_spike(flagged_company_ids, portfolio_size),
        check_model_boundary_ambiguity(boundary_kind),
        check_policy_violation(policy_violation_detected, policy_violation_detail),
        check_destructive_layer_change(destructive_layer_change[1], destructive_layer_change[0])
        if destructive_layer_change is not None else None,
    ):
        if finding is not None:
            findings.append(finding)
    return findings
