"""Full replay bundles for every flagged event (systemic spike, model-boundary ambiguity, or
policy violation). Each incident is a complete, self-contained record: the exact version,
model, and inputs that produced it, so eighteen months from now someone can ask "why did we
call this company healthy in Q2" and get a real answer, not a guess.

Stale-approval default: a pending_review incident that sits unresolved past
STALE_PENDING_REVIEW_BUSINESS_DAYS auto-escalates severity and gets re-notified (see
notifications.py) rather than being treated as implicit approval by silence.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pulse import policy_rules
from pulse.paths import INCIDENTS_DIR, ensure_data_dirs

Status = Literal["auto_resolved", "pending_review", "reviewed",
                  "pending_human_approval", "approved", "rejected"]

_SEVERITY_ORDER = ["low", "medium", "high", "critical"]


class IncidentError(ValueError):
    pass


def _index_path() -> Path:
    ensure_data_dirs()
    return INCIDENTS_DIR / "index.jsonl"


def _bundle_path(incident_id: str) -> Path:
    return INCIDENTS_DIR / f"{incident_id}.json"


def _next_incident_id() -> str:
    ensure_data_dirs()
    existing = list(INCIDENTS_DIR.glob("INC-*.json"))
    n = len(existing) + 1
    return f"INC-{n:04d}"


def create_incident(
    *, kind: str, company_ids: list[str], agent_version: str, model: str,
    input_snapshot: dict[str, Any], output_snapshot: dict[str, Any],
    risk_tier: str, routing: str, detected_at: str,
    remediation_detail: str = "", counterfactual: dict[str, Any] | None = None,
    policy_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create and persist a new incident replay bundle. detected_at is the SIMULATED cycle
    date (not wall-clock time), so the record stays meaningful when replayed later."""
    incident_id = _next_incident_id()
    if routing == "auto_rollback":
        status: Status = "auto_resolved"
    elif routing == "pending_human_approval":
        status = "pending_human_approval"
    else:
        status = "pending_review"

    bundle = {
        "incident_id": incident_id,
        "detected_at": detected_at,
        "kind": kind,
        "company_ids": company_ids,
        "agent_version": agent_version,
        "model": model,
        "input_snapshot": input_snapshot,
        "output_snapshot": output_snapshot,
        "risk_tier": risk_tier,
        "routing": routing,
        "status": status,
        "remediation_detail": remediation_detail,
        "resolved_by": None,
        "human_note": None,
        "counterfactual": counterfactual,
        "policy_check": policy_check,
        "escalation_log": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with _bundle_path(incident_id).open("w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    with _index_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps({"incident_id": incident_id, "kind": kind, "status": status,
                             "risk_tier": risk_tier, "detected_at": detected_at}) + "\n")
    return bundle


def get_incident(incident_id: str) -> dict[str, Any]:
    path = _bundle_path(incident_id)
    if not path.exists():
        raise IncidentError(f"no incident {incident_id} on record")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save(bundle: dict[str, Any]) -> None:
    with _bundle_path(bundle["incident_id"]).open("w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)


def list_incidents(status: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    ensure_data_dirs()
    results = []
    for path in sorted(INCIDENTS_DIR.glob("INC-*.json")):
        with path.open("r", encoding="utf-8") as f:
            bundle = json.load(f)
        if status is not None and bundle["status"] != status:
            continue
        if kind is not None and bundle["kind"] != kind:
            continue
        results.append(bundle)
    return results


def attach_policy_check(incident_id: str, policy_check: dict[str, Any]) -> dict[str, Any]:
    """Attach policy-compliance-checker's real, per-company judgment (keyed by company_id) to
    an already-created incident. A separate write from create_incident's own policy_check
    param because the check runs AFTER the incident exists (it cites the incident's own
    routing decision in its search query) — this is not a human review or an authorization,
    just recording what the compliance check found."""
    bundle = get_incident(incident_id)
    bundle["policy_check"] = policy_check
    _save(bundle)
    return bundle


def record_human_review(incident_id: str, resolved_by: str, human_note: str,
                         new_status: Status = "reviewed") -> dict[str, Any]:
    """The feedback-loop write: a human confirms (or corrects) an incident's disposition."""
    bundle = get_incident(incident_id)
    bundle["status"] = new_status
    bundle["resolved_by"] = resolved_by
    bundle["human_note"] = human_note
    bundle["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    _save(bundle)
    return bundle


def record_approval_decision(incident_id: str, decision: Literal["approved", "rejected"],
                              decided_by: str, note: str) -> dict[str, Any]:
    """The active-authorization write, for incidents routed to pending_human_approval —
    distinct from record_human_review's passive confirmation of an already-taken automated
    action. This is a human explicitly authorizing (or refusing) a destructive change that
    pulse/human_approval.py has, up to this point, taken no action on whatsoever. Recording
    "approved" here does not itself perform the underlying action — it only records that a
    human has authorized it; any actual execution is a separate, deliberate step outside this
    module."""
    bundle = get_incident(incident_id)
    bundle["status"] = decision
    bundle["resolved_by"] = decided_by
    bundle["human_note"] = note
    bundle["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    _save(bundle)
    return bundle


def escalate_if_stale(as_of: date,
                       threshold_business_days: int = policy_rules.STALE_PENDING_REVIEW_BUSINESS_DAYS
                       ) -> list[dict[str, Any]]:
    """Scan all pending_review incidents; any sitting unresolved past the threshold gets its
    risk_tier bumped one level and a re-notify entry appended to escalation_log. Never
    silently treated as approved. Returns the incidents that were escalated this call."""
    escalated = []
    for bundle in list_incidents(status="pending_review"):
        detected_at = date.fromisoformat(bundle["detected_at"])
        if not policy_rules.is_pending_review_stale(detected_at, as_of, threshold_business_days):
            continue
        current_idx = _SEVERITY_ORDER.index(bundle["risk_tier"])
        new_idx = min(current_idx + 1, len(_SEVERITY_ORDER) - 1)
        bundle["risk_tier"] = _SEVERITY_ORDER[new_idx]
        bundle["escalation_log"].append({
            "escalated_at": as_of.isoformat(),
            "reason": f"pending_review unresolved past {threshold_business_days} business days",
            "new_risk_tier": bundle["risk_tier"],
        })
        _save(bundle)
        escalated.append(bundle)
    return escalated
