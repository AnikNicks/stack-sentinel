from pulse import company_registry


def test_register_and_activate(isolated_company_registry):
    company_registry.register_new_version("meridian", "resolution-agent", {
        "version": "v1", "company_id": "meridian", "agent": "resolution-agent",
        "created": "2025-01-06", "changelog": "Initial release.",
    })
    assert company_registry.get_active("meridian", "resolution-agent") is None

    pointer = company_registry.activate("meridian", "resolution-agent", "v1", activated_by="initial-deployment")
    assert pointer["active_version"] == "v1"
    active = company_registry.get_active("meridian", "resolution-agent")
    assert active["version"] == "v1"
    assert active["activated_by"] == "initial-deployment"


def test_get_previous_active_needs_two_activations(isolated_company_registry):
    for v in ("v1", "v2"):
        company_registry.register_new_version("meridian", "resolution-agent", {
            "version": v, "company_id": "meridian", "agent": "resolution-agent",
            "created": "2025-01-06", "changelog": "x",
        })
    company_registry.activate("meridian", "resolution-agent", "v1", activated_by="initial-deployment")
    assert company_registry.get_previous_active("meridian", "resolution-agent") is None

    company_registry.activate("meridian", "resolution-agent", "v2", activated_by="eng-lead")
    assert company_registry.get_previous_active("meridian", "resolution-agent") == "v1"


def test_companies_are_isolated_namespaces(isolated_company_registry):
    for company_id in ("meridian", "wayfinder"):
        company_registry.register_new_version(company_id, "resolution-agent", {
            "version": "v1", "company_id": company_id, "agent": "resolution-agent",
            "created": "2025-01-06", "changelog": "x",
        })
        company_registry.activate(company_id, "resolution-agent", "v1", activated_by="initial-deployment")

    assert company_registry.get_active("meridian", "resolution-agent")["company_id"] == "meridian"
    assert company_registry.get_active("wayfinder", "resolution-agent")["company_id"] == "wayfinder"


def test_missing_required_field_raises(isolated_company_registry):
    import pytest
    with pytest.raises(company_registry.CompanyRegistryError):
        company_registry.register_new_version("meridian", "resolution-agent", {"version": "v1"})
