"""The stack-sentinel-directory MCP server. Exposes the 7 tools from the spec over real MCP
stdio transport, using the official `mcp` Python SDK (installed in .venv, version 2.0.0 —
its high-level `MCPServer` class is this SDK version's equivalent of the older `FastMCP`).

Honesty note (see README.md): this server has been import-tested, tool-schema-tested (see
scripts/verify_mcp_server.py), and exercised in-process via mcp_server.tools_impl by
pulse/orchestrator.py during the real simulation run — but it was NOT exercised end-to-end
over a live stdio round-trip from an actual Claude Code subagent session in this build,
because no live `claude` CLI session was available in this environment. It is written
against the real, installed SDK's actual API (verified by import and introspection, not
guessed from memory of older SDK versions), not blind against documentation.

append_trend_entry is the only write tool. Every tool call here is logged via
pulse/audit_log.py and, where relevant, wrapped by pulse/retry.py's transient/permanent
failure policy — see mcp_server/tools_impl.py for the real implementations this file wraps.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from mcp_server import tools_impl

# A live MCP protocol round-trip does not carry a trustworthy "which agent version called
# me" field (see tools_impl.py's module docstring) — this generic identity is used for every
# call made over the real wire protocol. pulse/orchestrator.py calls tools_impl directly
# in-process with the real calling agent + version instead, for audit entries that need that
# precision (see orchestrator.py).
_EXTERNAL_CALLER = {"agent": "mcp-client", "agent_version": "external"}

mcp = MCPServer(
    name="stack-sentinel-directory",
    title="Stack Sentinel — System Directory",
    description=(
        "Read/write tools over monitored systems' charters, SLO agreements, layer/operational "
        "metrics, the longitudinal trend store, and the policy corpus. append_trend_entry is "
        "the only write tool."
    ),
    version="1.0.0",
)


@mcp.tool()
def list_portfolio_companies() -> list[dict[str, Any]]:
    """List every company under monitoring, with id, name, monitoring_track, sector."""
    return tools_impl.list_portfolio_companies(caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_system_charter(company_id: str) -> dict[str, Any]:
    """CHARTER only. The stable system charter set at launch (target operational metrics +
    agent_behavior_boundaries + launch risks) — semantic memory, not the cycle-by-cycle
    episodic trend record."""
    return tools_impl.get_system_charter(company_id, caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_slo_agreement(company_id: str) -> dict[str, Any]:
    """SLO only. The stable SLO/error-budget thresholds and reporting cadence set at launch."""
    return tools_impl.get_slo_agreement(company_id, caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_system_metrics(company_id: str, cycle: str) -> dict[str, Any]:
    """The full structured snapshot for one company, one cycle (e.g. cycle="2025-S06"):
    layers (version + change_event per layer), operational_health, and behavior_incidents."""
    return tools_impl.get_system_metrics(company_id, cycle, caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_trend_history(company_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """The company's longitudinal trend record, oldest-first. Pass `limit` to retrieve only
    the most recent N entries — the bounded-recent-window retrieval scope most agents in
    this system are meant to use; omitting it returns the full history."""
    return tools_impl.get_trend_history(company_id, limit, caller=_EXTERNAL_CALLER)


@mcp.tool()
def append_trend_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """The only write tool. Idempotent, keyed by (company_id, cycle) — a duplicate call is a
    no-op that returns the existing entry, never a new record."""
    return tools_impl.append_trend_entry(entry, caller=_EXTERNAL_CALLER)


@mcp.tool()
def search_policy(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Semantic vector search over the fixed, versioned monitoring & escalation policy
    corpus. Matches on situation/meaning, not keyword overlap."""
    return tools_impl.search_policy(query, k, caller=_EXTERNAL_CALLER)


@mcp.tool()
def search_company_policy(company_id: str, query: str, k: int = 3) -> list[dict[str, Any]]:
    """Semantic vector search scoped to ONE company's own policy document — a company's own
    rules, checked the same way its charter boundaries are, never mixed with another
    company's clauses."""
    return tools_impl.search_company_policy(company_id, query, k, caller=_EXTERNAL_CALLER)


if __name__ == "__main__":
    mcp.run(transport="stdio")
