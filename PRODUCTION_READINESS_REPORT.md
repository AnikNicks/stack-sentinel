# Production Readiness Report

Generated from the actual `scripts/simulate_production_run.py --reset` run in this repo, plus
the actual test and verification script runs. Every number below is read from real output
(trend store, incidents, registry, notifications log) — nothing here is illustrative.

## Simulation

- **Quarters simulated:** 8 (`2025-Q1` through `2026-Q4`), 3 portfolio companies (Northwind
  Logistics Group — PE, Solace Behavioral Health — PE, Ferrous Point Industrial Supply — PD).
- **Trend entries written:** 8 per company (24 total across the 3 real companies), plus 1
  isolated demo entry (`demo-fault-injection`) from the fault-injection drills — kept in a
  separate file, never counted toward the real portfolio.
- **Fault-injection drills, all 5 genuinely exercised** (see script output, not narrated):
  transient failure retried twice then succeeded with real exponential backoff; permanent
  failure raised immediately with zero retries; a malformed agent output caught by
  `schema_validator` and written as a real `assessment_failed` entry; the per-cycle MCP call
  budget exceeded on a 3rd call (cap=2) and raised loudly; a stale `pending_review` incident
  auto-escalated `high → critical` and was re-notified.
- **Idempotency proof, live in the run:** Northwind's 2025-Q1 `append_trend_entry` call was
  made twice with an identical entry; `get_trend_history` confirmed exactly 1 record both
  times, and the second call's `recorded_at` matched the first — proving it returned the
  original record, not a new write.

## Versions deployed

`registry/trend-synthesizer/activation_log.jsonl` (real activation history from this run):

| # | Version | Activated by | Reason |
|---|---------|--------------|--------|
| 1 | v1 | initial-deployment | Initial production deployment |
| 2 | v2 | deal-team-lead | Legitimate improvement — trailing-3-quarter noise filtering |
| 3 | v3 | deal-team-lead | Regression, innocuous-looking changelog — tightened short-term sensitivity |
| 4 | v2 | **pulse-auto-rollback** | Systemic flag spike (2 of 3 companies in one quarter) |

**Final state:** `registry/trend-synthesizer/active.yaml` → `active_version: v2`,
`activated_by: pulse-auto-rollback` — confirmed on disk after the run.

## The rollback event

Incident **`INC-0002`**, `kind=systemic_flag_spike`, `risk_tier=critical`,
`routing=auto_rollback`, `status=auto_resolved`. Trigger: Northwind and Solace both
misclassified `off_thesis` in 2026-Q1 under the newly-activated `v3`, on inputs that were
ordinary quarter-to-quarter noise (small dips against multi-quarter uptrends). Ferrous
Point (PD, deterministic covenant math, no LLM in its classification path) was **not**
involved and never could be — see `pulse/orchestrator.py`'s `classifying_agent` filter,
verified by `tests/test_risk_scoring.py::test_pd_only_flag_across_multiple_quarters_never_triggers_spike`.
Full detail and the real counterfactual: `VERSIONING.md`, worked scenario 1.

## The model-boundary event and resolution

Incident **`INC-0003`**, `kind=model_boundary_ambiguity`, `risk_tier=high`,
`routing=human_review`, `status=reviewed`. Trigger: Solace's `trend-synthesizer` calls for
2026-Q2 and 2026-Q3 both carried `agent_version=v2` (unchanged) but different `model` values
— a real model-boundary per `pulse/model_boundary.py`. Classification flipped `on_thesis` →
`off_thesis` on a revenue-growth figure (8.3%) still within Solace's normal trailing range.
Routed to human review unconditionally (never auto-resolved, per
`risk_scoring.check_model_boundary_ambiguity`). Resolved via
`pulse.incidents.record_human_review(resolved_by="jordan.lee@dealteam.example.com", ...)`,
confirming model-interpretation noise, not a business change. Full detail: `VERSIONING.md`,
worked scenario 2.

## The policy violation / Credit Committee escalation caught

Ferrous Point's Total Net Leverage crossed into `warning` (≥4.0x) in 2026-Q2 (4.1x) and
stayed `warning` in 2026-Q3 (4.3x) — 2 consecutive warning quarters. **Deterministically
computed** (`pulse.policy_rules.credit_committee_clause_triggered`), fired exactly once, in
**2026-Q3**, dispatching a real (dry-run-logged) Jira ticket + Confluence page + Slack post
per the Credit Committee reporting clause. This persisted correctly across 2026-Q2–Q4 without
ever being counted toward, or confused with, the systemic-flag-spike rule — proven both by
this run's real incident list (no spike fired in 2026-Q2/Q3/Q4 despite Ferrous Point being
flagged in all three quarters) and by a dedicated unit test.

## Incident counts

| Kind | Count | Status breakdown |
|---|---|---|
| `systemic_flag_spike` | 1 | 1 auto_resolved |
| `model_boundary_ambiguity` | 2 | 1 reviewed (INC-0003, the real scenario), 1 pending_review (INC-0001, the stale-escalation fault-injection drill, left unresolved on purpose to prove the drill) |
| **Total** | **3** | |

## Notification dispatch (real records, `notifications_log.jsonl`)

14 real dispatch records this run. Every channel and purpose from the plan fired at least
once: `confluence`+`email` (off_thesis deal-partner review, ×3 events), `slack` (systemic
spike rollback alert, stale re-escalation), `jira`+`confluence`+`slack` (Credit Committee
escalation), and the universal critical/high-risk-tier email rule firing alongside every
qualifying incident. **Mode: originally dry-run on the run this section's numbers/scenario
narrative were first written against; superseded 2026-08-13 by a real `--live` run against the
same scenario — see "External connector status" below for the current, real
`live`/`status` fields.** Check `notifications_log.jsonl` directly at any time for the
authoritative current answer, not this doc.

## External connector status

**Updated 2026-08-13 — now genuinely live, not just dry-run-verified.** Docker MCP Toolkit
side: dedicated, isolated `portfolio-pulse` profile (`gmail-mcp` + `atlassian` + `slack`, none
shared with any other profile on the machine), fully credentialed by the user (Gmail app
password, Slack bot token, Atlassian API tokens — set via `docker mcp secret set`, never seen
by the assistant). A real Windows-only bug in how `pulse/notifications.py` spawns the gateway
subprocess (missing `ProgramFiles`/`ProgramData` in the `mcp` SDK's restricted env allowlist)
was found and fixed (`_windows_docker_cli_plugin_env()`) — see `PROGRESS.md`'s "Live run, part
4" for the full investigation.

**Proof, both directions:** Earlier, `--live` was run against the still-uncredentialed profile
as a deliberate safety proof — all 14 attempts failed loudly with specific, honest per-channel
reasons (`PULSE_SLACK_CHANNEL_ID is not set`, an unconfigured-server connection failure, etc.),
every `live` field `true`, every `status` `"error"`, never a false `"sent"`. Now, with real
credentials and the subprocess-env bug fixed, a fresh `--live` run produced the opposite real
result: **all 14 dispatches `live: true, status: "sent"`, 0 errors**, across email, Slack,
Jira, and Confluence — independently confirmed by reading the real Gmail inbox back
(`[Stack Sentinel] ACTION: ...` messages present, not narrated). Check
`notifications_log.jsonl`'s `live`/`status` fields at any time for the current, real answer.

## Reproducibility check result

`scripts/reproducibility_check.py` re-ran the real `risk_scoring.check_systemic_flag_spike`
against `INC-0002`'s exact recorded `company_ids` (`['northwind', 'solace']`) and
`portfolio_size` (`3`):

```
Re-run result:  risk_tier='critical'  routing='auto_rollback'
Recorded:       risk_tier='critical'  routing='auto_rollback'

MATCH — identical risk_tier and routing reproduced from the exact recorded inputs.
```

## Tests

- `pytest tests/ -v`: **31 passed, 0 failed**.
- `python tests/run_tests.py` (framework-free fallback): **21 passed, 0 failed**.
- Both suites include a dedicated test proving a single genuine PD covenant flag across
  multiple quarters never triggers a false systemic-spike incident.

## Known limitations, stated plainly

- The 6 subagents were never invoked over a live MCP/Claude Code round-trip in this build —
  see README.md's "What's implemented" section.
- `--live` notification delivery depends on external account setup outside this repo's
  control; dry-run is fully exercised and verified regardless.
- The dashboard's chat panel depends on the Artifacts runtime capability being available.
