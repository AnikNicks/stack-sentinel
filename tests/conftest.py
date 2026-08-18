"""Shared pytest fixtures. Every test that touches disk gets an isolated tmp_path so tests
never read or write the real simulation data under data/ and registry/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture
def isolated_trend_store(tmp_path, monkeypatch):
    from pulse import trend_store
    trend_dir = tmp_path / "trend_store"
    trend_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(trend_store, "TREND_STORE_DIR", trend_dir)
    monkeypatch.setattr(trend_store, "ensure_data_dirs", lambda: None)
    return trend_store


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    from pulse import registry
    monkeypatch.setattr(registry, "REGISTRY_DIR", tmp_path / "registry")
    return registry


@pytest.fixture
def isolated_incidents(tmp_path, monkeypatch):
    from pulse import incidents
    incidents_dir = tmp_path / "incidents"
    incidents_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(incidents, "INCIDENTS_DIR", incidents_dir)
    monkeypatch.setattr(incidents, "ensure_data_dirs", lambda: None)
    return incidents


@pytest.fixture
def isolated_audit_log(tmp_path, monkeypatch):
    from pulse import audit_log
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(audit_log, "ensure_data_dirs", lambda: None)
    return audit_log
