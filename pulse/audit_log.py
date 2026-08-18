"""Append-only log of every MCP tool call: calling agent, its pinned version, timestamp,
tool name, and args — independent of incidents.py, so even a fully clean cycle (nothing
flagged, nothing rolled back) leaves a complete call trace behind.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pulse.paths import AUDIT_LOG_PATH, ensure_data_dirs

_SECRET_KEY_MARKERS = ("password", "token", "secret", "key", "api_key", "credential")


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for k, v in args.items():
        if any(marker in k.lower() for marker in _SECRET_KEY_MARKERS):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


def log_call(
    *, agent: str, agent_version: str, tool_name: str, args: dict[str, Any] | None = None,
    result_summary: str = "", timestamp: str | None = None,
) -> dict[str, Any]:
    ensure_data_dirs()
    entry = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "agent_version": agent_version,
        "tool_name": tool_name,
        "args": _redact(args or {}),
        "result_summary": result_summary,
    }
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_log() -> list[dict[str, Any]]:
    if not AUDIT_LOG_PATH.exists():
        return []
    entries = []
    with AUDIT_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries
