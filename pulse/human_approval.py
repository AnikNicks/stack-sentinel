"""The one place this codebase formally refuses to act. Mirrors soft_fix.py's single-purpose
design, inverted: soft_fix.py is the one place automated remediation IS permitted (reverting
a regressed agent to a previously-live, known-good version); this is the one place automated
remediation is NEVER permitted, no matter how confident the risk score is.

pulse/risk_scoring.check_destructive_layer_change fires unconditionally on any layer
change_event assessed non-reversible (a schema drop, a credential rotation with no fallback,
any data-loss-potential change) and routes it to pending_human_approval. This module is what
that routing calls: it never executes the underlying action, never calls a write tool against
the monitored system, and never auto-approves — it only formally records that a decision is
now pending a human. The actual decision is recorded separately, later, by a human, via
pulse.incidents.record_approval_decision.
"""

from __future__ import annotations

from typing import Any


def gate_destructive_action(reason: str) -> dict[str, Any]:
    """The ONLY function in this module. Given the reason a change was flagged destructive,
    always returns the same shape: action_taken is always False. This function has no branch
    that returns True — there is no input that makes it execute anything."""
    return {
        "action_taken": False,
        "status": "pending_human_approval",
        "reason": reason,
    }
