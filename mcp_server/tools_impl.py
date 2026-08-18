"""Real implementations behind the 7 stack-sentinel-directory MCP tools.

Each function takes an explicit `caller` dict ({"agent": ..., "agent_version": ...}) rather
than trying to infer it from protocol context — the standard MCP tool-call wire format
doesn't carry a trustworthy "who is calling me" field, and we should not trust a
client-supplied claim about its own identity for audit purposes anyway (an agent's own
assertion about itself is exactly the kind of untrusted input CLAUDE.md's prompt-injection
guardrail treats with suspicion). Two real call sites provide this differently:

- mcp_server/server.py's live MCP tool wrappers pass a generic "mcp-client / external"
  caller, since a real protocol round-trip genuinely doesn't have better information — this
  is a known, documented limitation, not silently glossed over.
- pulse/orchestrator.py calls these same functions in-process during a sprint cycle (and the
  simulation), where the orchestrator genuinely does know which agent + pinned version it is
  currently invoking, so it passes that real context through.

append_trend_entry is the only write tool, and per CLAUDE.md's guardrails it is called only
by the orchestration layer with an agent's own validated structured output — never by an
agent directly, and never fed raw MCP response text.
"""

from __future__ import annotations

import json
from typing import Any

from pulse import audit_log, trend_store, vector_store
from pulse.paths import COMPANIES_PATH, LAYER_METRICS_DIR
from pulse.retry import PermanentError, call_with_retry

_companies_cache: dict[str, Any] | None = None


def _load_companies() -> dict[str, dict[str, Any]]:
    global _companies_cache
    if _companies_cache is None:
        with COMPANIES_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        _companies_cache = {c["company_id"]: c for c in raw["companies"]}
    return _companies_cache


def _get_company_or_raise(company_id: str) -> dict[str, Any]:
    companies = _load_companies()
    if company_id not in companies:
        raise PermanentError(f"unknown company_id '{company_id}' — not found in portfolio directory")
    return companies[company_id]


def _log(caller: dict[str, str], tool_name: str, args: dict[str, Any], result_summary: str) -> None:
    audit_log.log_call(
        agent=caller.get("agent", "unknown"),
        agent_version=caller.get("agent_version", "unknown"),
        tool_name=tool_name,
        args=args,
        result_summary=result_summary,
    )


def get_company_display_name(company_id: str) -> str:
    """Plain internal lookup, not an MCP tool (no audit log entry, doesn't count against
    budget) — used where a human-readable name is needed for a notification, not a
    classification decision."""
    return _get_company_or_raise(company_id)["name"]


def list_portfolio_companies(*, caller: dict[str, str]) -> list[dict[str, Any]]:
    companies = _load_companies()
    result = [
        {"company_id": c["company_id"], "name": c["name"], "monitoring_track": c["monitoring_track"],
         "sector": c["sector"]}
        for c in companies.values()
    ]
    _log(caller, "list_portfolio_companies", {}, f"{len(result)} companies")
    return result


def get_system_charter(company_id: str, *, caller: dict[str, str]) -> dict[str, Any]:
    """CHARTER only — raises PermanentError (never retried) if called on a non-CHARTER company."""
    company = _get_company_or_raise(company_id)
    if company["monitoring_track"] != "CHARTER":
        raise PermanentError(
            f"get_system_charter called on non-CHARTER company '{company_id}' "
            f"(monitoring_track={company['monitoring_track']}) — use get_slo_agreement instead"
        )
    charter = company["system_charter"]
    _log(caller, "get_system_charter", {"company_id": company_id}, "charter returned")
    return charter


def get_slo_agreement(company_id: str, *, caller: dict[str, str]) -> dict[str, Any]:
    """SLO only — raises PermanentError (never retried) if called on a non-SLO company."""
    company = _get_company_or_raise(company_id)
    if company["monitoring_track"] != "SLO":
        raise PermanentError(
            f"get_slo_agreement called on non-SLO company '{company_id}' "
            f"(monitoring_track={company['monitoring_track']}) — use get_system_charter instead"
        )
    agreement = company["slo_agreement"]
    _log(caller, "get_slo_agreement", {"company_id": company_id}, "SLO agreement returned")
    return agreement


def get_system_metrics(company_id: str, cycle: str, *, caller: dict[str, str]) -> dict[str, Any]:
    """One call, one cycle: the full structured snapshot (layers + operational_health +
    behavior_incidents) — replaces the old scalar-KPI get_financials."""
    _get_company_or_raise(company_id)
    path = LAYER_METRICS_DIR / f"{company_id}.json"
    if not path.exists():
        raise PermanentError(f"no layer_metrics file for company_id '{company_id}'")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    cycles = data["cycles"]
    if cycle not in cycles:
        raise PermanentError(f"no system metrics recorded for {company_id} in cycle '{cycle}'")
    _log(caller, "get_system_metrics", {"company_id": company_id, "cycle": cycle}, "system metrics returned")
    return cycles[cycle]


def get_trend_history(company_id: str, limit: int | None = None, *, caller: dict[str, str]) -> list[dict[str, Any]]:
    _get_company_or_raise(company_id)
    history = trend_store.get_trend_history(company_id, limit=limit)
    _log(caller, "get_trend_history", {"company_id": company_id, "limit": limit}, f"{len(history)} entries")
    return history


def append_trend_entry(entry: dict[str, Any], *, caller: dict[str, str]) -> dict[str, Any]:
    """The only write tool. Called only by pulse/orchestrator.py, never by an agent directly."""
    result = trend_store.append_trend_entry(entry)
    _log(caller, "append_trend_entry",
         {"company_id": entry.get("company_id"), "cycle": entry.get("cycle")},
         f"classification={result.get('classification')}")
    return result


def search_policy(query: str, k: int = 3, *, caller: dict[str, str]) -> list[dict[str, Any]]:
    matches = call_with_retry(vector_store.search_policy, query, k=k)
    _log(caller, "search_policy", {"query": query, "k": k}, f"{len(matches)} matches")
    return matches


def search_company_policy(company_id: str, query: str, k: int = 3, *, caller: dict[str, str]) -> list[dict[str, Any]]:
    """Semantic search scoped to one company's own policy document — the monitoring system
    checking a company's own rules, the same discipline goal-drift-tracker applies to that
    company's own charter boundaries."""
    _get_company_or_raise(company_id)
    matches = call_with_retry(vector_store.search_company_policy, company_id, query, k=k)
    _log(caller, "search_company_policy", {"company_id": company_id, "query": query, "k": k}, f"{len(matches)} matches")
    return matches
