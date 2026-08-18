"""The ONLY remediation module. auto_rollback_to_last_known_good() and nothing else — no
LLM, no other action ever permitted here. Kept deliberately single-purpose so this file can
never grow into a place where an automated "fix" does something riskier than reverting to a
version that was already live and known-good.
"""

from __future__ import annotations

from typing import Any

from pulse import registry

ROLLBACK_ACTOR = "pulse-auto-rollback"


class NoKnownGoodVersionError(RuntimeError):
    pass


def auto_rollback_to_last_known_good(agent: str, reason: str) -> dict[str, Any]:
    """Revert `agent` to the version that was active immediately before its current one.

    This is safe unconditionally: the target version was already in production before the
    current (bad) one replaced it, so reverting to it is never a leap into the unknown — it's
    undoing the most recent change. That's why risk_scoring.py routes systemic-flag-spike
    straight here with no human gate, unlike model-boundary and policy-violation findings.
    """
    previous_version = registry.get_previous_active(agent)
    if previous_version is None:
        raise NoKnownGoodVersionError(
            f"no prior activation on record for {agent} — cannot auto-rollback"
        )
    pointer = registry.activate(
        agent, previous_version, activated_by=ROLLBACK_ACTOR, reason=reason,
    )
    return pointer
