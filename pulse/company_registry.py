"""Version registry for the MONITORED COMPANIES' own internal agents — e.g. Meridian's
resolution-agent, Cascade's auto-remediation-agent. This is a distinct concept from
pulse/registry.py, which versions Stack Sentinel's OWN six classifiers. That module defends
against Stack Sentinel's own classifier drift; this one is the actual subject of monitoring —
tracking what version of a company's own agent is live, and rolling it back when a flagged
event says it should be.

Same deliberately-dumb, file-based design as pulse/registry.py, just keyed by
(company_id, agent) instead of (agent) alone:
registry/companies/<company_id>/<agent>/v1.yaml, v2.yaml, ... + active.yaml pointer.
register_new_version() never activates; soft_fix-style rollback is the only automated caller
of activate() (see pulse/company_rollback.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pulse.paths import REGISTRY_DIR

COMPANY_REGISTRY_DIR = REGISTRY_DIR / "companies"

REQUIRED_VERSION_FIELDS = ("version", "company_id", "agent", "created", "changelog")

# The canonical list of each company's own internal agents — names match each company's
# product-surface description (system_charter summaries, the Cascade Pipeline Agent app's
# "Sub-agent status" panel). Single source of truth: scripts/seed_company_registry.py and
# dashboard/api/main.py both read this instead of maintaining their own copy.
COMPANY_AGENTS: dict[str, list[str]] = {
    "meridian": ["intake-triage-agent", "resolution-agent", "escalation-agent"],
    "wayfinder": ["trip-planner-agent", "booking-agent"],
    "cascade": ["schema-inference-agent", "anomaly-detection-agent", "auto-remediation-agent"],
}


class CompanyRegistryError(ValueError):
    pass


def _agent_dir(company_id: str, agent: str) -> Path:
    d = COMPANY_REGISTRY_DIR / company_id / agent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _active_path(company_id: str, agent: str) -> Path:
    return _agent_dir(company_id, agent) / "active.yaml"


def _activation_log_path(company_id: str, agent: str) -> Path:
    return _agent_dir(company_id, agent) / "activation_log.jsonl"


def _version_path(company_id: str, agent: str, version: str) -> Path:
    return _agent_dir(company_id, agent) / f"{version}.yaml"


def list_versions(company_id: str, agent: str) -> list[dict[str, Any]]:
    bundles = []
    for path in _agent_dir(company_id, agent).glob("v*.yaml"):
        with path.open("r", encoding="utf-8") as f:
            bundles.append(yaml.safe_load(f))

    def _num(b: dict[str, Any]) -> int:
        return int(str(b["version"]).lstrip("v"))

    return sorted(bundles, key=_num)


def register_new_version(company_id: str, agent: str, bundle: dict[str, Any]) -> Path:
    missing = [f for f in REQUIRED_VERSION_FIELDS if f not in bundle]
    if missing:
        raise CompanyRegistryError(f"version bundle missing required fields: {missing}")
    version = bundle["version"]
    path = _version_path(company_id, agent, version)
    if path.exists():
        raise CompanyRegistryError(f"version {version} already registered for {company_id}/{agent}")
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(bundle, f, sort_keys=False)
    return path


def get_active(company_id: str, agent: str) -> dict[str, Any] | None:
    active_path = _active_path(company_id, agent)
    if not active_path.exists():
        return None
    with active_path.open("r", encoding="utf-8") as f:
        pointer = yaml.safe_load(f)
    version = pointer["active_version"]
    version_path = _version_path(company_id, agent, version)
    if not version_path.exists():
        raise CompanyRegistryError(f"active.yaml points at unregistered version {version} for {company_id}/{agent}")
    with version_path.open("r", encoding="utf-8") as f:
        bundle = yaml.safe_load(f)
    bundle = dict(bundle)
    bundle["activated_at"] = pointer.get("activated_at")
    bundle["activated_by"] = pointer.get("activated_by")
    return bundle


def activate(company_id: str, agent: str, version: str, activated_by: str,
             activated_at: str | None = None, reason: str = "") -> dict[str, Any]:
    version_path = _version_path(company_id, agent, version)
    if not version_path.exists():
        raise CompanyRegistryError(f"cannot activate unregistered version {version} for {company_id}/{agent}")

    activated_at = activated_at or datetime.now(timezone.utc).isoformat()
    pointer = {
        "company_id": company_id,
        "agent": agent,
        "active_version": version,
        "activated_by": activated_by,
        "activated_at": activated_at,
        "reason": reason,
    }
    with _active_path(company_id, agent).open("w", encoding="utf-8") as f:
        yaml.safe_dump(pointer, f, sort_keys=False)

    with _activation_log_path(company_id, agent).open("a", encoding="utf-8") as f:
        f.write(json.dumps(pointer) + "\n")

    return pointer


def get_previous_active(company_id: str, agent: str) -> str | None:
    log_path = _activation_log_path(company_id, agent)
    if not log_path.exists():
        return None
    entries = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    if len(entries) < 2:
        return None
    return entries[-2]["active_version"]
