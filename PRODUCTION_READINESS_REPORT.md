# Production Readiness Report

Generated from the actual `scripts/simulate_production_run.py --reset` run in this repo, plus
the actual test and verification script runs. Every number below is read from real output
(trend store, incidents, registry, notifications log) — nothing here is illustrative.

## Simulation

- **Sprint cycles simulated:** 10 (`2025-S01` through `2025-S10`), 3 companies (Meridian
  Labs and Wayfinder AI — CHARTER-tracked; Cascade Analytics — SLO-tracked).
- **Trend entries written:** 10 per company (30 total across the 3 real companies), plus 1
  isolated demo entry (`demo-fault-injection`) from the fault-injection drills — kept in a
  separate file, never counted toward the real portfolio.
- **Fault-injection drills, all 5 genuinely exercised** (see script output, not narrated):
  transient failure retried twice then succeeded with real exponential backoff; permanent
  failure raised immediately with zero retries; a malformed agent output caught by
  `schema_validator` and written as a real `assessment_failed` entry; the per-cycle MCP call
  budget exceeded on a 3rd call (cap=2) and raised loudly; a stale `pending_review` incident
  auto-escalated `high → critical` and was re-notified.
- **Idempotency proof, live in the run:** Meridian's 2025-S01 `append_trend_entry` call was
  made twice with an identical entry; `get_trend_history` confirmed exactly 1 record both
  times, and the second call's `recorded_at` matched the first — proving it returned the
  original record, not a new write.

## Versions deployed

`registry/change-impact-synthesizer/activation_log.jsonl` (real activation history from this run):

| # | Version | Activated by | Reason |
|---|---------|--------------|--------|
| 1 | v1 | initial-deployment | Initial production deployment |
| 2 | v2 | engineering-lead | Legitimate improvement — requires the change_event to plausibly explain the specific finding |
| 3 | v3 | engineering-lead | Regression, innocuous-looking changelog — tightened short-term sensitivity |
| 4 | v2 | **pulse-auto-rollback** | Systemic flag spike (2 of 3 companies in one cycle) |

**Final state:** `registry/change-impact-synthesizer/active.yaml` →
`active_version: v2`, `activated_by: pulse-auto-rollback` — confirmed on disk after the run.

## The rollback event

Incident **`INC-0002`**, `kind=systemic_flag_spike`, `risk_tier=critical`,
`routing=auto_rollback`, `status=auto_resolved`. Trigger: Meridian and Wayfinder both
misclassified `drifted` in 2025-S06 under the newly-activated `v3`, on inputs that were a
benign audit-log timestamp-ordering artifact from that cycle's own routine layer change —
never an actual boundary violation. Cascade (SLO, deterministic error-budget math, no LLM in
its classification path) was **not** involved and never could be — see
`pulse/orchestrator.py`'s `classifying_agent` filter, verified by
`tests/test_risk_scoring.py::test_slo_only_flag_across_multiple_cycles_never_triggers_spike`.
Full detail and the real counterfactual: `VERSIONING.md`, worked scenario 1.

## The model-boundary event and resolution

Incident **`INC-0004`**, `kind=model_boundary_ambiguity`, `risk_tier=high`,
`routing=human_review`, `status=reviewed`. Trigger: Wayfinder's `change-impact-synthesizer`
calls for 2025-S08 and 2025-S09 both carried `agent_version=v2` (unchanged) but different
`model` values — a real model-boundary per `pulse/model_boundary.py`. Classification flipped
`on_charter` → `drifted` when the same benign audit-log artifact recurred, this time
following a routine MCP tool version bump. Routed to human review unconditionally (never
auto-resolved, per `risk_scoring.check_model_boundary_ambiguity`). Resolved via
`pulse.incidents.record_human_review(resolved_by="priya.nair@platform-reliability.example.com", ...)`,
confirming model-interpretation noise, not a real behavior change. Full detail:
`VERSIONING.md`, worked scenario 2.

## The destructive-change event, blocked and then explicitly approved

Incident **`INC-0003`**, `kind=destructive_layer_change`, `risk_tier=critical`,
`routing=pending_human_approval`, `status=approved`. Trigger: Cascade's `database` layer
proposed `DROP TABLE raw_events_archive` (4.2M rows) in 2025-S08, flagged
`reversible: false`. `pulse.layer_versioning.detect_layer_change` classified it
`destructive_change_candidate` from that literal fact alone — no agent involved.
`pulse.human_approval.gate_destructive_action` was called and returned
`action_taken: False` — the migration was **not executed** by this system, and no code path
in this repository could have executed it. Only afterward, as a separate explicit step, was
`pulse.incidents.record_approval_decision("INC-0003", "approved", decided_by="morgan.reyes@data-governance.example.com", ...)`
called. Full detail: `VERSIONING.md`, worked scenario 3.

## The RRB escalation caught

Cascade's `monthly_error_budget_consumed_pct` crossed into `warning` (≥80%) in 2025-S06 (82%)
and stayed `warning` in 2025-S07 (91%) — 2 consecutive warning cycles. **Deterministically
computed** (`pulse.policy_rules.rrb_clause_triggered`), fired exactly once, in **2025-S07**,
dispatching a real (dry-run-logged) Jira ticket + Confluence page + Slack post per the
Reliability Review Board reporting clause. This persisted correctly across S07–S10 without
ever being counted toward, or confused with, the systemic-flag-spike rule — proven both by
this run's real incident list (no spike fired in S07/S08/S09/S10 despite Cascade being
flagged in all of them) and by a dedicated unit test.

## Incident counts

| Kind | Count | Status breakdown |
|---|---|---|
| `systemic_flag_spike` | 1 | 1 auto_resolved (INC-0002) |
| `destructive_layer_change` | 1 | 1 approved (INC-0003) |
| `model_boundary_ambiguity` | 2 | 1 reviewed (INC-0004, the real scenario), 1 pending_review (INC-0001, the stale-escalation fault-injection drill, left unresolved on purpose to prove the drill) |
| **Total** | **4** | |

## Notification dispatch (real records, `notifications_log.jsonl`)

**16 real dispatch records this run.** Every channel and purpose fired at least once:
`confluence`+`email` (charter-drift engineering review, 3 newly-drifted events — Meridian
S06, Wayfinder S06, Wayfinder S09), `slack` (systemic-spike rollback alert, destructive-change
pending-approval alert, stale re-escalation), `jira`+`confluence`+`slack` (RRB escalation),
and the universal critical/high-risk-tier email rule firing alongside every one of the 4
qualifying incidents. **Mode: dry-run** — `notifications_log.jsonl`'s `live` field is `false`
on every record; no real Gmail/Slack/Jira/Confluence call was made this run. `--live` requires
your own Docker MCP Toolkit profile and credentials, never checked into this repo (see
`.env.example`).

## Reproducibility check result

`scripts/reproducibility_check.py` re-ran the real `risk_scoring.check_systemic_flag_spike`
against `INC-0002`'s exact recorded `company_ids` (`['meridian', 'wayfinder']`) and
`portfolio_size` (`3`):

```
Re-run result:  risk_tier='critical'  routing='auto_rollback'
Recorded:       risk_tier='critical'  routing='auto_rollback'

MATCH — identical risk_tier and routing reproduced from the exact recorded inputs.
```

## Tests

- `pytest tests/ -v`: **57 passed, 0 failed**.
- `python tests/run_tests.py` (framework-free fallback): **31 passed, 0 failed**.
- Both suites include a dedicated test proving a single genuine SLO flag across multiple
  cycles never triggers a false systemic-spike incident.

## Web UIs

- **`dashboard/api` + `dashboard/web`** (Stack Sentinel's own live console): all 6 pages
  verified end-to-end in a real browser against this run's real data (Overview, Company,
  Incidents, Registry, System Health, Ask). The one write endpoint
  (`POST /incidents/{id}/decision`) was exercised directly against the real incident data,
  then the file was restored via `git checkout` since that call was a manual verification
  step, not part of the actual simulation run.
- **`companies/*`** (3 illustrative product demos): all three build clean
  (`npm run build`); Cascade's app verified live in a real browser on both its Product and
  Cycle Replay tabs.

## Known limitations, stated plainly

- The 6 subagents were never invoked over a live MCP/Claude Code round-trip in this build —
  see `README.md`'s "What's implemented" section.
- `--live` notification delivery depends on external account setup outside this repo's
  control; dry-run is fully exercised and verified regardless.
- `pulse/metrics.approval_turnaround`'s business-day figures aren't meaningful against this
  simulated run's data, because `detected_at` is a simulated cycle date while `reviewed_at` is
  a real wall-clock timestamp — see the function's own docstring. The underlying SLA math is
  correct; only this demo's two input timestamps are on different clocks.
- No git push, no GitHub Pages republish, and no separate git repo per company have happened
  as part of this build — all explicitly deferred, later, user-approved steps.
