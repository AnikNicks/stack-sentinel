"""Shared path constants. Internal helper, not part of the public module list in the plan —
exists only to avoid every module recomputing the project root."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TREND_STORE_DIR = DATA_DIR / "trend_store"
INCIDENTS_DIR = DATA_DIR / "incidents"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.jsonl"
NOTIFICATIONS_LOG_PATH = PROJECT_ROOT / "notifications_log.jsonl"
COMPANIES_PATH = DATA_DIR / "portfolio_companies.json"
LAYER_METRICS_DIR = DATA_DIR / "layer_metrics"
REGISTRY_DIR = PROJECT_ROOT / "registry"
POLICY_DIR = PROJECT_ROOT / "policy"
POLICY_DOC_PATH = POLICY_DIR / "monitoring_escalation_policy.md"
CHROMA_DIR = POLICY_DIR / ".chroma"


def ensure_data_dirs() -> None:
    TREND_STORE_DIR.mkdir(parents=True, exist_ok=True)
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
