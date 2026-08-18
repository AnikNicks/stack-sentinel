# Portfolio Monitoring & Escalation Policy

**Document owner:** Portfolio Operations
**Applies to:** All PE and private-debt (PD) portfolio companies under active quarterly
monitoring.
**Status:** Fixed and versioned. This document is not user-editable at runtime by any
automated system — real policy updates require a deliberate, reviewed re-ingestion step
(see `pulse/vector_store.py`), never a live auto-updating index.

## Purpose and scope

This policy governs how Portfolio Pulse's quarterly monitoring outputs — thesis-tracking
classifications, covenant classifications, and detected model/version boundaries — are
escalated to human decision-makers. It exists because automated classification, however
consistent, is not a substitute for human judgment on decisions that affect capital,
counterparties, or the firm's relationship with a portfolio company's management team.

## Covenant reporting

Covenant classifications are computed deterministically from loan-agreement terms and
reported financials (see `pulse/policy_rules.py`). The following reporting obligation is
independent of whether the trend is improving or worsening in any given quarter:

Any covenant classified as warning for two or more consecutive reporting periods must be
reported to the Credit Committee at the next scheduled meeting, regardless of trend
direction. A single warning quarter does not trigger this clause; two or more consecutive
warning quarters does, even if the second quarter shows improvement over the first, because
the obligation is about sustained proximity to breach, not about the direction of travel.

## Thesis-tracking review

A portfolio company classified off_thesis must receive deal-partner review within 5
business days of classification. This applies whether the off_thesis classification stems
from a genuine deterioration in underwritten KPIs or from any other cause. The review clock
starts at classification, not at the next portfolio meeting, so that a thesis break is never
sitting unreviewed for weeks by default.

## Model and version boundary handling

Portfolio Pulse's classification agents are versioned, and the underlying language model
each version is pinned to may itself change over the life of a multi-year monitoring
engagement, independent of any deliberate version upgrade. When a classification changes
between two consecutive reporting periods and that change coincides with a change in the
pinned model (rather than a deliberate, reviewed version upgrade), the classification change
cannot be treated as equivalent in reliability to a business-driven change.

Any classification change attributable to a change in the underlying model or agent
version, rather than a change in the company's actual financial position, must not be used
as the sole basis for an escalation decision without human confirmation. A model- or
version-attributable shift may still warrant investigation, but capital or governance
decisions may not rest on it until a human has confirmed the underlying business facts
independently support the new classification.

## Systemic anomalies

A sudden, portfolio-wide increase in flagged companies within a single reporting period is
treated as evidence of a monitoring-system fault (e.g. an agent-version regression) rather
than evidence of simultaneous, unrelated portfolio-wide deterioration, which does not occur
in practice — real credit and thesis deterioration develops company-by-company, over
multiple periods. Such anomalies should trigger an automatic reversion of the monitoring
system to its last known-good configuration, independent of any single company's specific
facts, so that no company's classification that quarter is relied upon until the anomaly is
resolved.

## Escalation review timeliness

An escalation or incident awaiting human review that remains unresolved beyond 10 business
days must not be treated as implicitly approved by the passage of time. Unresolved items
past this threshold should have their priority increased and the responsible reviewers
re-notified, so that silence is never mistaken for sign-off.
