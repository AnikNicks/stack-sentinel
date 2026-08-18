"""Real implementations behind the 7 portfolio-directory MCP tools.

Each function takes an explicit `caller` dict ({"agent": ..., "agent_version": ...}) rather
than trying to infer it from protocol context — the standard MCP tool-call wire format
doesn't carry a trustworthy "who is calling me" field, and we should not trust a
client-supplied claim about its own identity for audit purposes anyway (an agent's own
assertion about itself is exactly the kind of untrusted input CLAUDE.md's prompt-injection
guardrail treats with suspicion). Two real call sites provide this differently:

- mcp_server/server.py's live MCP tool wrappers pass a generic "mcp-client / external"
  caller, since a real protocol round-trip genuinely doesn't have better information — this
  is a known, documented limitation, not silently glossed over.
- pulse/orchestrator.py calls these same functions in-process during a quarterly cycle (and
  the simulation), where the orchestrator genuinely does know which agent + pinned version
  it is currently invoking, so it passes that real context through.

append_trend_entry is the only write tool, and per CLAUDE.md's guardrails it is called only
by the orchestration layer with an agent's own validated structured output — never by an
agent directly, and never fed raw MCP response text.
"""

from __future__ import annotations

import json
from typing import Any

from pulse import audit_log, trend_store, vector_store
from pulse.paths import COMPANIES_PATH, FINANCIALS_DIR
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
        {"company_id": c["company_id"], "name": c["name"], "relationship_type": c["relationship_type"],
         "sector": c["sector"]}
        for c in companies.values()
    ]
    _log(caller, "list_portfolio_companies", {}, f"{len(result)} companies")
    return result


def get_investment_thesis(company_id: str, *, caller: dict[str, str]) -> dict[str, Any]:
    """PE only — raises PermanentError (never retried) if called on a non-PE company."""
    company = _get_company_or_raise(company_id)
    if company["relationship_type"] != "PE":
        raise PermanentError(
            f"get_investment_thesis called on non-PE company '{company_id}' "
            f"(relationship_type={company['relationship_type']}) — use get_loan_agreement instead"
        )
    thesis = company["investment_thesis"]
    _log(caller, "get_investment_thesis", {"company_id": company_id}, "thesis returned")
    return thesis


def get_loan_agreement(company_id: str, *, caller: dict[str, str]) -> dict[str, Any]:
    """PD only — raises PermanentError (never retried) if called on a non-PD company."""
    company = _get_company_or_raise(company_id)
    if company["relationship_type"] != "PD":
        raise PermanentError(
            f"get_loan_agreement called on non-PD company '{company_id}' "
            f"(relationship_type={company['relationship_type']}) — use get_investment_thesis instead"
        )
    agreement = company["loan_agreement"]
    _log(caller, "get_loan_agreement", {"company_id": company_id}, "loan agreement returned")
    return agreement


def get_financials(company_id: str, period: str, *, caller: dict[str, str]) -> dict[str, Any]:
    _get_company_or_raise(company_id)
    path = FINANCIALS_DIR / f"{company_id}.json"
    if not path.exists():
        raise PermanentError(f"no financials file for company_id '{company_id}'")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    quarters = data["quarters"]
    if period not in quarters:
        raise PermanentError(f"no financials recorded for {company_id} in period '{period}'")
    _log(caller, "get_financials", {"company_id": company_id, "period": period}, "financials returned")
    return quarters[period]


def get_trend_history(company_id: str, limit: int | None = None, *, caller: dict[str, str]) -> list[dict[str, Any]]:
    _get_company_or_raise(company_id)
    history = trend_store.get_trend_history(company_id, limit=limit)
    _log(caller, "get_trend_history", {"company_id": company_id, "limit": limit}, f"{len(history)} entries")
    return history


def append_trend_entry(entry: dict[str, Any], *, caller: dict[str, str]) -> dict[str, Any]:
    """The only write tool. Called only by pulse/orchestrator.py, never by an agent directly."""
    result = trend_store.append_trend_entry(entry)
    _log(caller, "append_trend_entry",
         {"company_id": entry.get("company_id"), "quarter": entry.get("quarter")},
         f"classification={result.get('classification')}")
    return result


def search_policy(query: str, k: int = 3, *, caller: dict[str, str]) -> list[dict[str, Any]]:
    matches = call_with_retry(vector_store.search_policy, query, k=k)
    _log(caller, "search_policy", {"query": query, "k": k}, f"{len(matches)} matches")
    return matches
