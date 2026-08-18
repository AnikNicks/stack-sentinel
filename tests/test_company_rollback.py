import pytest

from pulse import company_registry, company_rollback


def _register(company_id, agent, version):
    company_registry.register_new_version(company_id, agent, {
        "version": version, "company_id": company_id, "agent": agent,
        "created": "2025-01-06", "changelog": "x",
    })


def test_auto_rollback_reverts_to_previous_version(isolated_company_registry):
    _register("cascade", "auto-remediation-agent", "v1")
    _register("cascade", "auto-remediation-agent", "v2")
    company_registry.activate("cascade", "auto-remediation-agent", "v1", activated_by="initial-deployment")
    company_registry.activate("cascade", "auto-remediation-agent", "v2", activated_by="eng-lead")

    pointer = company_rollback.auto_rollback_company_agent("cascade", "auto-remediation-agent", reason="test")
    assert pointer["active_version"] == "v1"
    assert pointer["activated_by"] == company_rollback.ROLLBACK_ACTOR

    active = company_registry.get_active("cascade", "auto-remediation-agent")
    assert active["version"] == "v1"
    assert active["activated_by"] == company_rollback.ROLLBACK_ACTOR


def test_auto_rollback_records_a_custom_activated_by_for_the_human_approved_path(isolated_company_registry):
    """The high-risk path calls this same function AFTER a human approves — the audit trail
    must show who authorized it, not silently read as the fully-automatic actor."""
    _register("cascade", "auto-remediation-agent", "v1")
    _register("cascade", "auto-remediation-agent", "v2")
    company_registry.activate("cascade", "auto-remediation-agent", "v1", activated_by="initial-deployment")
    company_registry.activate("cascade", "auto-remediation-agent", "v2", activated_by="eng-lead")

    pointer = company_rollback.auto_rollback_company_agent(
        "cascade", "auto-remediation-agent", reason="human-approved",
        activated_by="dana.kwon@platform-reliability.example.com",
    )
    assert pointer["activated_by"] == "dana.kwon@platform-reliability.example.com"
    assert company_registry.get_active("cascade", "auto-remediation-agent")["activated_by"] == "dana.kwon@platform-reliability.example.com"


def test_auto_rollback_raises_without_prior_version(isolated_company_registry):
    _register("cascade", "auto-remediation-agent", "v1")
    company_registry.activate("cascade", "auto-remediation-agent", "v1", activated_by="initial-deployment")
    with pytest.raises(company_rollback.NoKnownGoodCompanyVersionError):
        company_rollback.auto_rollback_company_agent("cascade", "auto-remediation-agent", reason="test")
