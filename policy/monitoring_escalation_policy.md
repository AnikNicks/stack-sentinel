# Monitoring & Escalation Policy

**Document owner:** Platform Reliability
**Applies to:** All monitored AI systems under active bi-weekly monitoring, both
CHARTER-tracked and SLO-tracked.
**Status:** Fixed and versioned. This document is not user-editable at runtime by any
automated system — real policy updates require a deliberate, reviewed re-ingestion step
(see `pulse/vector_store.py`), never a live auto-updating index.

## Purpose and scope

This policy governs how Stack Sentinel's bi-weekly monitoring outputs — charter-drift
classifications, SLO classifications, layer-level change events, and detected model/version
boundaries — are escalated to human decision-makers. It exists because automated
classification, however consistent, is not a substitute for human judgment on decisions that
affect production systems, customer data, or a monitored system's real-world behavior.

## Layer-level change reporting

SLO classifications are computed deterministically from SLO-agreement thresholds and reported
operational metrics (see `pulse/policy_rules.py`). The following reporting obligation is
independent of whether the trend is improving or worsening in any given cycle:

Any SLO classified as warning for two or more consecutive reporting periods must be reported
to the Reliability Review Board at the next scheduled meeting, regardless of trend direction.
A single warning cycle does not trigger this clause; two or more consecutive warning cycles
does, even if the second cycle shows improvement over the first, because the obligation is
about sustained proximity to breach, not about the direction of travel.

## Charter-tracking review

A monitored system classified drifted must receive engineering review within 5 business days
of classification. This applies whether the drifted classification stems from a genuine
behavior-boundary violation or from any other cause. The review clock starts at
classification, not at the next reporting cycle, so that a charter drift is never sitting
unreviewed for weeks by default.

## Model and version boundary handling

Stack Sentinel's classification agents are versioned, and the underlying language model each
version is pinned to may itself change over the life of a multi-year monitoring engagement,
independent of any deliberate version upgrade. When a classification changes between two
consecutive reporting periods and that change coincides with a change in the pinned model
(rather than a deliberate, reviewed version upgrade), the classification change cannot be
treated as equivalent in reliability to a change in the monitored system's real behavior.

Any classification change attributable to a change in the underlying model or agent version,
rather than a change in the monitored system's actual behavior, must not be used as the sole
basis for an escalation decision without human confirmation. A model- or version-attributable
shift may still warrant investigation, but operational decisions may not rest on it until a
human has confirmed the underlying system facts independently support the new classification.

## Destructive and irreversible layer changes

Any layer-level change assessed as non-reversible (data-loss potential, a schema drop without
a verified rollback path, credential rotation without a fallback, etc.) must never be
auto-remediated. It must be routed to `pending_human_approval` and require an explicit,
logged decision from a designated human reviewer before any downstream action proceeds. This
applies regardless of which layer the change touches — repository/CI-CD, database, memory,
tools, MCP integrations, or the production application — and regardless of how routine or
low-risk the change appears to the system proposing it. No automated actor, including the
monitoring system itself, may execute a change flagged this way; the absence of an approval
decision is never treated as authorization.

## Systemic anomalies

A sudden, portfolio-wide increase in flagged companies within a single reporting period is
treated as evidence of a monitoring-system fault (e.g. an agent-version regression) rather
than evidence of simultaneous, unrelated portfolio-wide deterioration, which does not occur
in practice — real behavior deterioration develops company-by-company, over multiple periods.
Such anomalies should trigger an automatic reversion of the monitoring system to its last
known-good configuration, independent of any single company's specific facts, so that no
company's classification that cycle is relied upon until the anomaly is resolved.

## Escalation review timeliness

An escalation or incident awaiting human review that remains unresolved beyond 10 business
days must not be treated as implicitly approved by the passage of time. Unresolved items past
this threshold should have their priority increased and the responsible reviewers
re-notified, so that silence is never mistaken for sign-off.
