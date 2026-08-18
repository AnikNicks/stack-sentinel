"""The portfolio-directory MCP server. Exposes the 7 tools from the spec over real MCP
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
    name="portfolio-directory",
    title="Portfolio Pulse — Portfolio Directory",
    description=(
        "Read/write tools over portfolio company theses, loan agreements, financials, the "
        "longitudinal trend store, and the policy corpus. append_trend_entry is the only "
        "write tool."
    ),
    version="1.0.0",
)


@mcp.tool()
def list_portfolio_companies() -> list[dict[str, Any]]:
    """List every portfolio company under monitoring, with id, name, relationship_type, sector."""
    return tools_impl.list_portfolio_companies(caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_investment_thesis(company_id: str) -> dict[str, Any]:
    """PE only. The stable investment thesis set at close — semantic memory, not the
    quarter-by-quarter episodic trend record."""
    return tools_impl.get_investment_thesis(company_id, caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_loan_agreement(company_id: str) -> dict[str, Any]:
    """PD only. The stable loan agreement / covenant terms set at close."""
    return tools_impl.get_loan_agreement(company_id, caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_financials(company_id: str, period: str) -> dict[str, Any]:
    """Raw reported financials for one company, one quarter (e.g. period="2025-Q2")."""
    return tools_impl.get_financials(company_id, period, caller=_EXTERNAL_CALLER)


@mcp.tool()
def get_trend_history(company_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """The company's longitudinal trend record, oldest-first. Pass `limit` to retrieve only
    the most recent N entries — the bounded-recent-window retrieval scope most agents in
    this system are meant to use; omitting it returns the full history."""
    return tools_impl.get_trend_history(company_id, limit, caller=_EXTERNAL_CALLER)


@mcp.tool()
def append_trend_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """The only write tool. Idempotent, keyed by (company_id, quarter) — a duplicate call is
    a no-op that returns the existing entry, never a new record."""
    return tools_impl.append_trend_entry(entry, caller=_EXTERNAL_CALLER)


@mcp.tool()
def search_policy(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Semantic vector search over the fixed, versioned monitoring & escalation policy
    corpus. Matches on situation/meaning, not keyword overlap."""
    return tools_impl.search_policy(query, k, caller=_EXTERNAL_CALLER)


if __name__ == "__main__":
    mcp.run(transport="stdio")
