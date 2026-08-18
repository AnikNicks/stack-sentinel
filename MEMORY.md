# MEMORY.md — Memory Taxonomy

Stack Sentinel doesn't have a literal separate "memory subsystem" in code — but every part
of it maps cleanly onto the standard four-part memory taxonomy, and being explicit about that
mapping is what keeps the deterministic/agentic boundary honest. This document is that
mapping.

## Working memory

The bounded context assembled for a single agent invocation: the current quarter's
financials plus the bounded recent window described in each agent's retrieval scope (last
4-6 quarters for `pe-thesis-tracker`/`pd-covenant-tracker`/`trend-synthesizer`; exactly the
two entries bracketing a boundary for `model-boundary-interpreter`; the latest entry per
company for `portfolio-rollup-writer`; no trend data at all for
`policy-compliance-checker`). Assembled fresh by `pulse/orchestrator.py` for every
invocation, discarded after — an agent never carries state between invocations. See
`.claude/agents/*.md` for each agent's exact retrieval-scope comment.

## Episodic memory

`pulse/trend_store.py` — the full trend store. Raw, timestamped, append-only, never edited in
place. Every entry records exactly which agent version and model produced it
(`classifying_agent`, `agent_version`, `model`), never re-derived from a live registry lookup
later — that's what makes `pulse/model_boundary.py`'s reproducibility check possible at all:
the record of "what produced this" travels with the data.

## Semantic memory

The stable facts fetched via `get_investment_thesis(company_id)` (PE) and
`get_loan_agreement(company_id)` (PD) — the investment thesis or loan agreement set at close.
Distinct from episodic memory in one crucial way: semantic memory doesn't change quarter to
quarter (the thesis a deal was underwritten on is fixed at close), while episodic memory is
exactly the quarter-by-quarter record of how reality tracked against that fixed thesis.

## Procedural memory — explicitly NOT present

There is no learned-pattern store anywhere in this system that any agent writes to or reads
from. No "the system has learned that X usually means Y" mechanism exists. This is a
deliberate omission, not a gap: `pulse/risk_scoring.py`'s three deterministic rules
(systemic-flag-spike, model-boundary ambiguity, policy violation) serve the role a
procedural-memory system might otherwise fill — **encoded, inspectable rules instead of
learned, opaque ones.** If asked directly why: a procedural-memory system that quietly
reweights its own risk thresholds based on outcomes is exactly the kind of drift this whole
project exists to prevent — an escalation rule that changed itself last quarter for reasons
nobody wrote down is indistinguishable, eighteen months later, from the model-boundary
problem this system already has enough trouble catching. Every threshold in
`risk_scoring.py` (the systemic-spike count, the business-day SLAs in `policy_rules.py`) is a
plain constant in source code, changed only by a human editing a file and committing it —
that commit *is* the procedural-memory update, and it's fully auditable.

## The concrete "when to ignore memory" case

`policy-compliance-checker` (`.claude/agents/policy-compliance-checker.md`) deliberately does
**not** call `get_trend_history` at all — only `search_policy` plus the current cycle's
already-computed classification/routing decision. This is the system's clearest example of
choosing *not* to retrieve available memory: pulling episodic trend data into a policy-
compliance judgment would add noise, not signal — the question "does this routing satisfy
policy" doesn't get better answered by knowing the company's revenue three years ago. Every
other agent's retrieval scope is about *bounding* memory; this one is about *excluding* a
whole category of it.
