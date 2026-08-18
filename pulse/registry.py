"""Agent version registry: registry/<agent>/v1.yaml, v2.yaml, ... + active.yaml pointer.

This is deliberately dumb and file-based: a version bundle is a YAML file with a
changelog describing the REAL behavioral change, and active.yaml is a one-line pointer to
which version is currently live. register_new_version() NEVER activates — activation is
always a separate, explicit call, either by a human (register a fix, then activate it) or by
soft_fix.auto_rollback_to_last_known_good() (the only automated caller of activate()).

activate() also appends to registry/<agent>/activation_log.jsonl, which is what
soft_fix.py reads to find "the previously active version" for a rollback — active.yaml
itself only ever holds the current pointer, per the plan's "one-line pointer" description.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pulse.paths import REGISTRY_DIR

REQUIRED_VERSION_FIELDS = (
    "version",
    "agent",
    "created",
    "changelog",
    "prompt_file",
    "tool_scope",
    "model",
    "objective_statement",
)


class RegistryError(ValueError):
    pass


def _agent_dir(agent: str) -> Path:
    d = REGISTRY_DIR / agent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _active_path(agent: str) -> Path:
    return _agent_dir(agent) / "active.yaml"


def _activation_log_path(agent: str) -> Path:
    return _agent_dir(agent) / "activation_log.jsonl"


def _version_path(agent: str, version: str) -> Path:
    return _agent_dir(agent) / f"{version}.yaml"


def list_versions(agent: str) -> list[dict[str, Any]]:
    """All registered version bundles for this agent, sorted by version number."""
    bundles = []
    for path in _agent_dir(agent).glob("v*.yaml"):
        with path.open("r", encoding="utf-8") as f:
            bundles.append(yaml.safe_load(f))

    def _num(b: dict[str, Any]) -> int:
        return int(str(b["version"]).lstrip("v"))

    return sorted(bundles, key=_num)


def register_new_version(agent: str, bundle: dict[str, Any]) -> Path:
    """Write a new version bundle. Never activates it — activate() is a separate call."""
    missing = [f for f in REQUIRED_VERSION_FIELDS if f not in bundle]
    if missing:
        raise RegistryError(f"version bundle missing required fields: {missing}")
    version = bundle["version"]
    path = _version_path(agent, version)
    if path.exists():
        raise RegistryError(f"version {version} already registered for {agent}")
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(bundle, f, sort_keys=False)
    return path


def get_active(agent: str) -> dict[str, Any] | None:
    """Currently active version's full bundle, or None if nothing has been activated yet."""
    active_path = _active_path(agent)
    if not active_path.exists():
        return None
    with active_path.open("r", encoding="utf-8") as f:
        pointer = yaml.safe_load(f)
    version = pointer["active_version"]
    version_path = _version_path(agent, version)
    if not version_path.exists():
        raise RegistryError(f"active.yaml points at unregistered version {version} for {agent}")
    with version_path.open("r", encoding="utf-8") as f:
        bundle = yaml.safe_load(f)
    bundle = dict(bundle)
    bundle["activated_at"] = pointer.get("activated_at")
    bundle["activated_by"] = pointer.get("activated_by")
    return bundle


def activate(agent: str, version: str, activated_by: str, activated_at: str | None = None,
             reason: str = "") -> dict[str, Any]:
    """Flip active.yaml to point at `version`. The only place active.yaml is written.

    activated_by is always recorded verbatim — e.g. "pulse-auto-rollback" for the automated
    rollback path, or a human identifier for a manual activation — so the audit trail can
    always answer "who/what made this version live."
    """
    version_path = _version_path(agent, version)
    if not version_path.exists():
        raise RegistryError(f"cannot activate unregistered version {version} for {agent}")

    activated_at = activated_at or datetime.now(timezone.utc).isoformat()
    pointer = {
        "agent": agent,
        "active_version": version,
        "activated_by": activated_by,
        "activated_at": activated_at,
        "reason": reason,
    }
    with _active_path(agent).open("w", encoding="utf-8") as f:
        yaml.safe_dump(pointer, f, sort_keys=False)

    with _activation_log_path(agent).open("a", encoding="utf-8") as f:
        f.write(json.dumps(pointer) + "\n")

    return pointer


def get_previous_active(agent: str) -> str | None:
    """The version that was active immediately before the current one, per
    activation_log.jsonl. Returns None if there's no prior activation to roll back to."""
    log_path = _activation_log_path(agent)
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
