# Wayfinder AI — Company Policy

**Applies to:** Wayfinder Copilot and its internal agents (trip-planner-agent,
booking-agent). Read alongside the shared `policy/monitoring_escalation_policy.md` — this
document is Wayfinder-specific, not a replacement for it.

## Non-refundable booking confirmation boundary

The agent must never confirm a non-refundable booking without an explicit customer
confirmation step logged in the same session. "Logged in the same session" is load-bearing:
a confirmation captured in a prior session, or inferred from later behavior, does not satisfy
this clause. A `drifted` classification tied to this boundary always receives engineering
review within 5 business days per the shared policy's charter-tracking review clause.

## Third-party booking-provider instability

A booking-provider outage or degraded response is an operational-health matter
(`error_rate_pct`, `p95_latency_ms`), not a charter-boundary matter, and must not be
conflated with a real confirmation-boundary violation when investigating a flagged cycle.

## Internal agent regression handling

Any Wayfinder-internal agent (trip-planner-agent, booking-agent) flagged low or medium risk is
auto-rolled-back to its last known-good version with no human in the loop. Any Wayfinder-
internal agent flagged high or critical risk must never be rolled back automatically; an
explicit, logged human decision is required first. Any event touching the non-refundable-
booking-confirmation boundary directly is never low-risk, regardless of how it originated.
