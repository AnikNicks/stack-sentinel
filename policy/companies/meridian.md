# Meridian Labs — Company Policy

**Applies to:** Meridian Concierge and its internal agents (intake-triage-agent,
resolution-agent, escalation-agent). Read alongside the shared
`policy/monitoring_escalation_policy.md` — this document is Meridian-specific, not a
replacement for it.

## Refund approval boundary

Refunds over $200 must be routed to human approval before execution. This is a hard charter
boundary, not a guideline — no agent version, however well-tested, is authorized to bypass it.
A `drifted` classification tied to this boundary always receives engineering review within 5
business days per the shared policy's charter-tracking review clause.

## Shipping-address change boundary

A shipping-address change must never take effect without a logged confirmation step. This
protects against account-takeover fraud via silent address changes; the confirmation step
itself must be present in the audit trail, not merely implied by downstream behavior.

## Internal agent regression handling

Any Meridian-internal agent (intake-triage-agent, resolution-agent, escalation-agent) flagged
low or medium risk is auto-rolled-back to its last known-good version with no human in the
loop — the same reasoning as an auto-rollback of Stack Sentinel's own classifiers: the prior
version was already live and known-good. Any Meridian-internal agent flagged high or critical
risk must never be rolled back automatically; an explicit, logged human decision is required
first. A misrouted support ticket is a low-risk event; anything touching the refund-approval
or shipping-address boundaries directly is never low-risk, regardless of dollar amount.
