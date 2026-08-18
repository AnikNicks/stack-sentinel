# Cascade Analytics — Company Policy

**Applies to:** Cascade Pipeline Agent and its internal agents (schema-inference-agent,
anomaly-detection-agent, auto-remediation-agent). Read alongside the shared
`policy/monitoring_escalation_policy.md` — this document is Cascade-specific, not a
replacement for it.

## Error-budget reporting

`monthly_error_budget_consumed_pct` classified warning (≥80%) for two or more consecutive
reporting cycles must be reported to the Reliability Review Board at the next scheduled
meeting, regardless of trend direction — the shared policy's clause, restated here because it
is the primary SLO Cascade is held against.

## Destructive schema changes

Any database-layer change flagged non-reversible (a schema drop, an unrecoverable migration)
must be routed to `pending_human_approval` and never auto-executed, per the shared policy's
"Destructive and irreversible layer changes" clause. This applies regardless of how routine
the migration appears in its own changelog.

## Auto-remediation scope boundary

`auto-remediation-agent` is authorized to retry, quarantine, and re-queue failed pipeline
runs. It is NOT authorized to truncate, drop, or otherwise discard malformed data without a
logged human sign-off — doing so is a high-risk event by definition, regardless of how it
reduces manual review load, because data discarded by a remediation step cannot later be
recovered for audit.

## Internal agent regression handling

Any Cascade-internal agent (schema-inference-agent, anomaly-detection-agent,
auto-remediation-agent) flagged low or medium risk is auto-rolled-back to its last known-good
version with no human in the loop. Any Cascade-internal agent flagged high or critical risk —
including any auto-remediation-agent version that exceeds the scope boundary above — must
never be rolled back automatically; an explicit, logged human decision is required first.
