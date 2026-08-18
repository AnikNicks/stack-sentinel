"""Automated rollback for a MONITORED COMPANY's own internal agent — the low/medium-risk half
of this project's risk-tiered response to a company-agent regression. Mirrors
pulse/soft_fix.py exactly in spirit (one function, no LLM, no other action ever permitted):
reverting a company's agent to the version that was live immediately before the flagged one is
safe unconditionally, because that version was already running in production and known-good.

The high/medium-risk split lives in pulse/risk_scoring.check_company_agent_regression: low and
medium risk route here, auto-rollback, no human in the loop. high and critical risk route to
pulse/human_approval.py instead — this module is never called for those, by construction (see
pulse/orchestrator.py's wiring).
"""

from __future__ import annotations

from typing import Any

from pulse import company_registry

ROLLBACK_ACTOR = "pulse-auto-rollback"


class NoKnownGoodCompanyVersionError(RuntimeError):
    pass


def auto_rollback_company_agent(company_id: str, agent: str, reason: str,
                                 activated_by: str = ROLLBACK_ACTOR) -> dict[str, Any]:
    """Revert `company_id`'s `agent` to the version active immediately before its current
    one. Safe unconditionally, same reasoning as soft_fix.auto_rollback_to_last_known_good.

    activated_by defaults to ROLLBACK_ACTOR for the true low/medium-risk automatic path (no
    human involved at all). For the high/critical-risk path, where this function is only
    ever called AFTER pulse.incidents.record_approval_decision has recorded an explicit human
    "approved" — the rollback itself is still performed by this function (a version rollback
    is safe and reversible, unlike a destructive action), but the caller should pass the
    human's identifier here so the activation record honestly shows a human authorized it,
    rather than silently reading as "pulse-auto-rollback" — which is the audit trail this
    project's own worked scenarios exist to keep truthful."""
    previous_version = company_registry.get_previous_active(company_id, agent)
    if previous_version is None:
        raise NoKnownGoodCompanyVersionError(
            f"no prior activation on record for {company_id}/{agent} — cannot auto-rollback"
        )
    return company_registry.activate(
        company_id, agent, previous_version, activated_by=activated_by, reason=reason,
    )
