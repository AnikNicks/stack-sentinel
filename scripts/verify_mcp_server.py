"""Real sanity check of the MCP server: imports it, lists its registered tools, and asserts
the 7 tools from the spec are present with the right names. This is NOT a live stdio
round-trip test (no live claude CLI available in this build — see README.md); it does prove
the server module is syntactically valid, importable, and produces correct MCP tool schemas
via the real installed `mcp` SDK.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.server import mcp

EXPECTED_TOOLS = {
    "list_portfolio_companies",
    "get_system_charter",
    "get_slo_agreement",
    "get_system_metrics",
    "get_trend_history",
    "append_trend_entry",
    "search_policy",
}


def main() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - names
    extra = names - EXPECTED_TOOLS
    print(f"registered tools: {sorted(names)}")
    assert not missing, f"missing expected tools: {missing}"
    assert not extra, f"unexpected extra tools: {extra}"
    for t in tools:
        assert t.description, f"tool {t.name} has no description"
    print(f"OK — all {len(EXPECTED_TOOLS)} expected tools registered with descriptions.")


if __name__ == "__main__":
    main()
