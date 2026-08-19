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
                   "destructive_layer_change", "company_agent_regression",
                   "cost_anomaly", "context_pressure", "user_escalation_spike",
                   "pii_exposure", "prompt_injection_succeeded", "agent_loop_detected",
                   "canary_divergence", "groundedness_failure"]
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


def _tiered_finding(kind: str, risk_tier: RiskTier, justification: str,
                     detail: dict[str, Any], routing: Routing = "human_review") -> RiskFinding:
    return RiskFinding(kind=kind, risk_tier=risk_tier, routing=routing,
                        justification=justification, detail=detail)


# --- Continuous per-cycle metrics — same shape as SLO error-budget math: a threshold or
# trailing-average comparison, evaluated every cycle, never auto-fixable by this system so
# routing is always human_review regardless of tier. -------------------------------------

def check_cost_anomaly(cost_usd: float, trailing_avg: float | None) -> RiskFinding | None:
    """Flags a cycle's LLM/tool-call spend well above its own trailing 6-cycle average. No
    baseline yet (first few cycles) -> nothing to compare against, no finding."""
    if trailing_avg is None or trailing_avg <= 0:
        return None
    pct_over = (cost_usd - trailing_avg) / trailing_avg * 100
    if pct_over >= 100:
        risk_tier: RiskTier = "high"
    elif pct_over >= 50:
        risk_tier = "medium"
    else:
        return None
    return _tiered_finding(
        "cost_anomaly", risk_tier,
        f"Cycle cost ${cost_usd:.2f} is {pct_over:.0f}% above the trailing average "
        f"${trailing_avg:.2f} — a spend spike with no corresponding auto-remediation; a human "
        "should account for why.",
        {"cost_usd": cost_usd, "trailing_avg": trailing_avg},
    )


def check_context_pressure(utilization_pct: float, truncated: bool) -> RiskFinding | None:
    """`truncated` is a literal, provider-reported fact (did the context window actually
    overflow), never inferred from the percentage alone — a truncation always outranks a
    near-full-but-not-truncated cycle regardless of the exact percentage."""
    if truncated:
        return _tiered_finding(
            "context_pressure", "high",
            f"Context window actually truncated this cycle at {utilization_pct:.0f}% "
            "utilization — output may be missing content the agent never saw.",
            {"utilization_pct": utilization_pct, "truncated": True},
        )
    if utilization_pct >= 90:
        return _tiered_finding(
            "context_pressure", "medium",
            f"Context utilization at {utilization_pct:.0f}% — approaching the window limit "
            "without truncating yet.",
            {"utilization_pct": utilization_pct, "truncated": False},
        )
    return None


def check_user_escalation_spike(rate_pct: float, thresholds: dict[str, float]) -> RiskFinding | None:
    """Same warning/breach shape as classify_slo_status, applied to the fraction of
    interactions users themselves escalated to a human — a direct signal independent of what
    the classifiers say about the cycle."""
    if rate_pct >= thresholds["breach_at_or_above"]:
        risk_tier: RiskTier = "high"
    elif rate_pct >= thresholds["warning_at_or_above"]:
        risk_tier = "medium"
    else:
        return None
    return _tiered_finding(
        "user_escalation_spike", risk_tier,
        f"User-escalation rate at {rate_pct:.1f}% (warning>={thresholds['warning_at_or_above']}, "
        f"breach>={thresholds['breach_at_or_above']}) — users themselves are routing around "
        "the agent at an elevated rate.",
        {"rate_pct": rate_pct},
    )


# --- Discrete per-cycle events — each backed by a real deterministic detector in pulse/
# (pii_scan.py, injection_monitoring.py, agent_loop_detection.py, canary_comparison.py), or by
# the one new agent (groundedness-checker) for the one case that's a genuine semantic
# judgment. --------------------------------------------------------------------------------

def check_pii_exposure(matches: list[str]) -> RiskFinding | None:
    """Any real PII pattern match in a company's own output sample is critical regardless of
    which pattern matched — the exposure already happened, so this is incident response, not a
    gate on a future action (unlike destructive_layer_change, there's nothing left to block)."""
    if not matches:
        return None
    return _tiered_finding(
        "pii_exposure", "critical",
        f"PII pattern(s) detected in a real output sample: {', '.join(matches)}. Already "
        "exposed — this is incident response, not a pending action.",
        {"matches": matches},
    )


def check_prompt_injection(marker_hits: list[str], succeeded: bool) -> RiskFinding | None:
    """Fires ONLY when the injection attempt actually changed the monitored system's real
    behavior this cycle (succeeded=True, decided by the caller cross-referencing this cycle's
    behavior_incidents — never by re-reading the injected text itself). An attempt that did not
    succeed is still real signal, but is aggregated into pulse/metrics.security_scan_summary
    rather than becoming its own incident — not every observation needs a full incident
    lifecycle, the same reasoning behind the RRB clause dispatching directly instead."""
    if not marker_hits or not succeeded:
        return None
    return _tiered_finding(
        "prompt_injection_succeeded", "critical",
        f"Injection marker(s) {marker_hits} present this cycle AND a real behavior_incident "
        "was recorded the same cycle — the attempt changed real behavior, not just phrasing.",
        {"marker_hits": marker_hits},
    )


def check_agent_loop(repeat_count: int, threshold: int = 5) -> RiskFinding | None:
    """Mirrors check_company_agent_regression's exact tiering contract: low/medium risk ->
    auto_rollback (reusing pulse/company_rollback.py — the prior version wasn't looping, so
    reverting to it is safe by the same reasoning as every other auto-rollback in this system);
    high/critical -> pending_human_approval, never auto-executed."""
    if repeat_count < threshold:
        return None
    if repeat_count < threshold * 2:
        risk_tier: RiskTier = "medium"
        routing: Routing = "auto_rollback"
    else:
        risk_tier = "high"
        routing = "pending_human_approval"
    return _tiered_finding(
        "agent_loop_detected", risk_tier,
        f"{repeat_count} repeated/alternating calls detected in one cycle (threshold {threshold}) "
        "— a real hand-off loop, not a single legitimate escalation.",
        {"repeat_count": repeat_count, "threshold": threshold},
        routing=routing,
    )


def check_canary_divergence(diverged: bool) -> RiskFinding | None:
    """A candidate version's decision disagreeing with the last known-good version's decision
    on the identical input is never auto-resolved either way — pending_human_approval, and
    approving it only records the decision (pulse/human_approval.py's contract); nothing here
    auto-promotes the candidate."""
    if not diverged:
        return None
    return _tiered_finding(
        "canary_divergence", "high",
        "Candidate version's decision diverges from the last known-good version's decision on "
        "the identical input — held for human review before any promotion.",
        {"diverged": True},
        routing="pending_human_approval",
    )


def check_groundedness(judgment: str) -> RiskFinding | None:
    """The one finding sourced from an LLM judgment (groundedness-checker) rather than a
    literal fact — routing is still fixed deterministically regardless of the judgment's
    content, same discipline as check_model_boundary_ambiguity."""
    if judgment == "fabricated":
        return _tiered_finding(
            "groundedness_failure", "critical",
            "groundedness-checker judged this output fabricated — not supported by, and "
            "contradicting, the retrieved source.",
            {"judgment": judgment},
        )
    if judgment == "unsupported":
        return _tiered_finding(
            "groundedness_failure", "medium",
            "groundedness-checker judged this output unsupported by the retrieved source — "
            "not necessarily wrong, but not verifiable from what was retrieved.",
            {"judgment": judgment},
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
