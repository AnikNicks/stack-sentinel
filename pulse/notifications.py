"""Deterministic notification dispatch — zero LLM — and the ONLY module allowed to call the
real external Gmail/Jira/Confluence/Slack MCP tools (same "only the orchestration layer
touches write-capable tools" discipline as append_trend_entry). Called only by
pulse/orchestrator.py, with structured incident/classification data it already computed —
never raw agent text.

Real external calls go through the `mcp` SDK's own client, connecting as a subprocess to
`docker mcp gateway run --profile stack-sentinel` — the dedicated, isolated Docker MCP
Toolkit profile set up for this project (see PROGRESS.md / README.md for what that profile
contains and why it's isolated from any other profile on this machine). This module does NOT
use Claude Code's own MCP tool-calling — it is a real MCP *client* written in plain Python,
so pulse/ (which must remain zero-LLM) can dispatch real notifications without needing an
LLM session in the loop at all.

Safety default: LIVE mode is OFF by default. Call enable_live_mode() to actually fire real
Gmail/Jira/Confluence/Slack calls (scripts/simulate_production_run.py's --live flag does
this). In dry-run mode, every dispatch function still runs its full real decision logic and
writes a real record to notifications_log.jsonl — only the actual external tool call is
skipped. Every dispatch, live or dry-run, is logged, so the record always shows what WOULD
have happened even when nothing was actually sent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Any

from pulse.paths import NOTIFICATIONS_LOG_PATH, PROJECT_ROOT


def _load_dotenv(path) -> None:
    """Minimal `.env` loader — no python-dotenv dependency, real env vars always win. Mirrors
    dashboard/ask_server.py's loader; kept separate since pulse/ has zero cross-module coupling
    to dashboard/ by design."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(PROJECT_ROOT / ".env")

EMAIL_ADDRESS = os.environ.get("PULSE_EMAIL_ADDRESS", "claudecodenotification@gmail.com")
SLACK_CHANNEL_ID = os.environ.get("PULSE_SLACK_CHANNEL_ID", "")
JIRA_PROJECT_KEY = os.environ.get("PULSE_JIRA_PROJECT_KEY", "")
CONFLUENCE_SPACE_KEY = os.environ.get("PULSE_CONFLUENCE_SPACE_KEY", "")
DOCKER_MCP_PROFILE = os.environ.get("PULSE_DOCKER_MCP_PROFILE", "stack-sentinel")

_LIVE = False


def enable_live_mode() -> None:
    global _LIVE
    _LIVE = True


def disable_live_mode() -> None:
    global _LIVE
    _LIVE = False


def is_live() -> bool:
    return _LIVE


class NotificationConfigError(RuntimeError):
    """Raised when LIVE mode is on but a required target (channel id / project key / space
    key) isn't configured — fails loudly rather than silently dry-running a live-requested
    call."""


def _windows_docker_cli_plugin_env() -> dict[str, str]:
    """The mcp SDK's default Windows subprocess env allowlist is missing two vars Docker
    needs: `ProgramFiles` (to discover the `mcp` CLI plugin at all — without it `docker mcp
    ...` silently falls back to plain `docker --help`) and `ProgramData` (the docker-mcp
    gateway binary itself panics with "unable to get 'ProgramData'" reading Docker Desktop's
    admin settings without it). Both confirmed by direct reproduction: identical argv, only
    the env differs."""
    if sys.platform != "win32":
        return {}
    return {k: v for k, v in (
        ("ProgramFiles", os.environ.get("ProgramFiles")),
        ("ProgramW6432", os.environ.get("ProgramW6432")),
        ("ProgramData", os.environ.get("ProgramData")),
    ) if v}


async def _call_gateway_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command="docker",
        args=["mcp", "gateway", "run", "--profile", DOCKER_MCP_PROFILE],
        env=_windows_docker_cli_plugin_env(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return {
                "is_error": bool(getattr(result, "isError", False)),
                "content": [getattr(c, "text", str(c)) for c in getattr(result, "content", [])],
            }


def _call_gateway_tool_sync(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call_gateway_tool(tool_name, arguments))


def _record(*, channel: str, target: str, purpose: str, detail: dict[str, Any],
            incident_id: str | None = None) -> dict[str, Any]:
    status = "dry_run"
    error = None
    if _LIVE:
        try:
            if channel == "email":
                result = _call_gateway_tool_sync("sendMessage", {
                    "to": target, "subject": detail["subject"], "body": detail["body"],
                })
            elif channel == "slack":
                if not target:
                    raise NotificationConfigError("PULSE_SLACK_CHANNEL_ID is not set — cannot dispatch live Slack message")
                result = _call_gateway_tool_sync("slack_post_message", {"channel_id": target, "text": detail["text"]})
            elif channel == "jira":
                if not target:
                    raise NotificationConfigError("PULSE_JIRA_PROJECT_KEY is not set — cannot create live Jira ticket")
                result = _call_gateway_tool_sync("jira_create_issue", {
                    "issue_type": "Task", "project_key": target,
                    "summary": detail["summary"], "description": detail.get("description", ""),
                })
            elif channel == "confluence":
                if not target:
                    raise NotificationConfigError("PULSE_CONFLUENCE_SPACE_KEY is not set — cannot create live Confluence page")
                result = _call_gateway_tool_sync("confluence_create_page", {
                    "space_key": target, "title": detail["title"], "content": detail["content"],
                })
            else:
                raise ValueError(f"unknown channel {channel}")
            status = "error" if result.get("is_error") else "sent"
            if status == "error":
                error = result.get("content")
        except Exception as exc:  # noqa: BLE001 — real external call, real failure surface
            status = "error"
            error = str(exc)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel": channel, "target": target, "purpose": purpose,
        "status": status, "live": _LIVE, "error": error,
        "incident_id": incident_id, "detail": detail,
    }
    with NOTIFICATIONS_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def dispatch_drifted_review(company_id: str, company_name: str, cycle: str, as_of_date: date,
                             rationale: str) -> list[dict[str, Any]]:
    """'A monitored system classified drifted must receive engineering review within 5
    business days of classification.' -> Confluence review-record page + email alert."""
    records = []
    records.append(_record(
        channel="confluence", target=CONFLUENCE_SPACE_KEY, purpose="drifted_engineering_review",
        detail={
            "title": f"[Stack Sentinel] Engineering review — {company_name} ({cycle})",
            "content": (
                f"# Engineering review required\n\n**System:** {company_name} ({company_id})\n"
                f"**Cycle:** {cycle}\n**Classified:** drifted on {as_of_date.isoformat()}\n"
                f"**SLA:** review required within 5 business days of classification\n\n"
                f"## Rationale\n{rationale}\n"
            ),
        },
    ))
    records.append(_record(
        channel="email", target=EMAIL_ADDRESS, purpose="drifted_engineering_review",
        detail={
            "subject": f"[Stack Sentinel] ACTION: {company_name} classified drifted ({cycle})",
            "body": (
                f"{company_name} ({company_id}) was classified drifted for {cycle} on "
                f"{as_of_date.isoformat()}. Engineering review required within 5 business days "
                f"per the Monitoring & Escalation Policy.\n\nRationale: {rationale}"
            ),
        },
    ))
    return records


def dispatch_rrb_escalation(company_id: str, cycle: str, as_of_date: date) -> list[dict[str, Any]]:
    """'Any SLO classified as warning for two or more consecutive reporting periods must be
    reported to the Reliability Review Board at the next scheduled meeting.' -> Jira ticket +
    Confluence-tracked meeting-date entry (standing in for a real calendar invite — no
    Calendar MCP server exists in the catalog, see PROGRESS.md) + Slack post."""
    records = []
    records.append(_record(
        channel="jira", target=JIRA_PROJECT_KEY, purpose="rrb_escalation",
        detail={
            "summary": f"RRB report: {company_id} SLO warning, 2+ consecutive cycles ({cycle})",
            "description": (
                f"{company_id}'s SLO has been classified warning for 2 or more consecutive "
                f"reporting periods as of {cycle}. Per the Monitoring & Escalation Policy this "
                f"must be reported to the Reliability Review Board at the next scheduled "
                f"meeting, regardless of trend direction."
            ),
        },
    ))
    records.append(_record(
        channel="confluence", target=CONFLUENCE_SPACE_KEY, purpose="rrb_escalation",
        detail={
            "title": f"[Stack Sentinel] RRB agenda item — {company_id} ({cycle})",
            "content": (
                f"# Reliability Review Board reporting — {company_id}\n\n**Cycle:** {cycle}\n"
                f"**Trigger:** SLO warning for 2+ consecutive cycles (as of {as_of_date.isoformat()})\n"
                f"**Action:** add to next scheduled RRB meeting agenda.\n"
            ),
        },
    ))
    records.append(_record(
        channel="slack", target=SLACK_CHANNEL_ID, purpose="rrb_escalation",
        detail={"text": f"[Stack Sentinel] {company_id}: SLO warning for 2+ consecutive cycles "
                         f"as of {cycle} — RRB reporting clause triggered. Jira + Confluence created."},
    ))
    records += _dispatch_universal_email_if_high_risk(
        company_id=company_id, purpose="rrb_escalation", risk_tier="high",
        subject=f"[Stack Sentinel] RRB escalation — {company_id} ({cycle})",
        body=f"{company_id}'s SLO warning has hit 2+ consecutive cycles as of {cycle}. "
             f"RRB reporting clause triggered; Jira ticket and Confluence page created.",
    )
    return records


def _dispatch_universal_email_if_high_risk(*, company_id: str, purpose: str, risk_tier: str,
                                            subject: str, body: str, incident_id: str | None = None) -> list[dict[str, Any]]:
    """Universal rule, per explicit user request: any critical/high risk_tier event ALSO
    sends a real email regardless of which other channel already fired, implemented as one
    unconditional check so it can't be silently skipped when a new event kind is added
    later. Kept as its own function (not folded into each dispatch_* function's body) for
    exactly that reason — every dispatch_* call site that has a risk_tier routes through
    this same check."""
    if risk_tier not in ("critical", "high"):
        return []
    return [_record(
        channel="email", target=EMAIL_ADDRESS, purpose=f"{purpose}_universal_high_risk_alert",
        detail={"subject": subject, "body": body}, incident_id=incident_id,
    )]


def dispatch_for_incident(incident: dict[str, Any]) -> list[dict[str, Any]]:
    """Kind-specific dispatch for a risk_scoring-produced incident, plus the universal
    critical/high -> email rule applied unconditionally at the end."""
    records: list[dict[str, Any]] = []
    kind = incident["kind"]
    company_ids = incident["company_ids"]

    if kind == "systemic_flag_spike":
        records.append(_record(
            channel="slack", target=SLACK_CHANNEL_ID, purpose="systemic_flag_spike_rollback",
            detail={"text": f"[Stack Sentinel] AUTO-ROLLBACK: systemic flag spike detected "
                             f"({len(company_ids)} companies flagged: {', '.join(company_ids)}) — "
                             f"change-impact-synthesizer auto-rolled back to last known-good "
                             f"version. Incident {incident['incident_id']}."},
            incident_id=incident["incident_id"],
        ))
    elif kind == "destructive_layer_change":
        records.append(_record(
            channel="slack", target=SLACK_CHANNEL_ID, purpose="destructive_layer_change_pending_approval",
            detail={"text": f"[Stack Sentinel] BLOCKED — PENDING HUMAN APPROVAL: a non-reversible "
                             f"layer change was detected for {', '.join(company_ids)} and has NOT "
                             f"been executed. No automated action was taken; an explicit, logged "
                             f"human decision is required before anything proceeds. "
                             f"Incident {incident['incident_id']}."},
            incident_id=incident["incident_id"],
        ))
    elif kind == "company_agent_regression":
        agent = incident["input_snapshot"].get("agent", "unknown-agent")
        if incident["routing"] == "auto_rollback":
            text = (f"[Stack Sentinel] AUTO-ROLLBACK: {', '.join(company_ids)}/{agent} flagged "
                    f"{incident['risk_tier']}-risk — auto-rolled back to its last known-good "
                    f"version, no human gate required. Incident {incident['incident_id']}.")
        else:
            text = (f"[Stack Sentinel] BLOCKED — PENDING HUMAN APPROVAL: {', '.join(company_ids)}/{agent} "
                    f"flagged {incident['risk_tier']}-risk — NOT rolled back automatically. An "
                    f"explicit, logged human decision is required before anything proceeds. "
                    f"Incident {incident['incident_id']}.")
        records.append(_record(
            channel="slack", target=SLACK_CHANNEL_ID, purpose="company_agent_regression",
            detail={"text": text}, incident_id=incident["incident_id"],
        ))

    records += _dispatch_universal_email_if_high_risk(
        company_id=",".join(company_ids), purpose=kind, risk_tier=incident["risk_tier"],
        subject=f"[Stack Sentinel] {incident['risk_tier'].upper()} incident: {kind} ({incident['incident_id']})",
        body=(
            f"Incident {incident['incident_id']} ({kind}) detected at {incident['detected_at']} — "
            f"companies: {', '.join(company_ids)}. Routing: {incident['routing']}. "
            f"{incident['remediation_detail']}"
        ),
        incident_id=incident["incident_id"],
    )
    return records


def dispatch_stale_reescalation(incident: dict[str, Any]) -> list[dict[str, Any]]:
    """A pending_review incident unresolved past the stale threshold: Slack re-notify, never
    treated as implicit approval by silence."""
    return [_record(
        channel="slack", target=SLACK_CHANNEL_ID, purpose="stale_pending_review_reescalation",
        detail={"text": f"[Stack Sentinel] RE-NOTIFY: incident {incident['incident_id']} "
                         f"({incident['kind']}) has been pending_review past the stale threshold — "
                         f"escalated to {incident['risk_tier']}. Not implicitly approved by silence."},
        incident_id=incident["incident_id"],
    )]
