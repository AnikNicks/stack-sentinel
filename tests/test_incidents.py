"""Covers create_incident's routing->status derivation (now three branches) and the new
active-authorization write, record_approval_decision."""

from datetime import date


def _create(isolated_incidents, routing, kind="destructive_layer_change"):
    return isolated_incidents.create_incident(
        kind=kind, company_ids=["cascade"], agent_version="v1", model="test-model",
        input_snapshot={}, output_snapshot={}, risk_tier="critical", routing=routing,
        detected_at=date(2025, 1, 1).isoformat(),
    )


def test_auto_rollback_routing_becomes_auto_resolved(isolated_incidents):
    bundle = _create(isolated_incidents, "auto_rollback", kind="systemic_flag_spike")
    assert bundle["status"] == "auto_resolved"


def test_pending_human_approval_routing_stays_pending_human_approval(isolated_incidents):
    bundle = _create(isolated_incidents, "pending_human_approval")
    assert bundle["status"] == "pending_human_approval"


def test_human_review_routing_becomes_pending_review(isolated_incidents):
    bundle = _create(isolated_incidents, "human_review", kind="model_boundary_ambiguity")
    assert bundle["status"] == "pending_review"


def test_record_approval_decision_approved(isolated_incidents):
    bundle = _create(isolated_incidents, "pending_human_approval")
    updated = isolated_incidents.record_approval_decision(
        bundle["incident_id"], "approved", decided_by="data-governance-lead",
        note="Confirmed pre-approved; cold-storage migration verified complete before drop.",
    )
    assert updated["status"] == "approved"
    assert updated["resolved_by"] == "data-governance-lead"
    assert updated["reviewed_at"] is not None

    reloaded = isolated_incidents.get_incident(bundle["incident_id"])
    assert reloaded["status"] == "approved"


def test_record_approval_decision_rejected(isolated_incidents):
    bundle = _create(isolated_incidents, "pending_human_approval")
    updated = isolated_incidents.record_approval_decision(
        bundle["incident_id"], "rejected", decided_by="data-governance-lead",
        note="No verified backup — do not proceed.",
    )
    assert updated["status"] == "rejected"


def test_attach_policy_check_updates_and_persists(isolated_incidents):
    bundle = _create(isolated_incidents, "pending_human_approval")
    assert bundle["policy_check"] is None

    check = {"cascade": {"checked": True, "compliant": True, "matched_clause_titles": ["x"], "rationale": "y"}}
    updated = isolated_incidents.attach_policy_check(bundle["incident_id"], check)
    assert updated["policy_check"] == check

    reloaded = isolated_incidents.get_incident(bundle["incident_id"])
    assert reloaded["policy_check"] == check


def test_record_approval_decision_does_not_itself_perform_any_action(isolated_incidents):
    """record_approval_decision only ever writes status/resolved_by/human_note/reviewed_at —
    it has no side effect beyond the incident bundle itself (no call to any layer, no
    mutation of anything but the incident record)."""
    bundle = _create(isolated_incidents, "pending_human_approval")
    updated = isolated_incidents.record_approval_decision(
        bundle["incident_id"], "approved", decided_by="x", note="y",
    )
    # Only these four fields change; everything else on the original bundle is untouched.
    changed_fields = {"status", "resolved_by", "human_note", "reviewed_at"}
    for key in bundle:
        if key not in changed_fields:
            assert updated[key] == bundle[key], f"unexpected side effect on field '{key}'"
    assert set(updated.keys()) - set(bundle.keys()) == {"reviewed_at"}
