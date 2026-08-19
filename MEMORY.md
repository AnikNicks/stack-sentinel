# MEMORY.md — Memory Taxonomy

Stack Sentinel doesn't have a literal separate "memory subsystem" in code — but every part
of it maps cleanly onto the standard four-part memory taxonomy, and being explicit about that
mapping is what keeps the deterministic/agentic boundary honest. This document is that
mapping.

## Working memory

The bounded context assembled for a single agent invocation: the current cycle's system
metrics plus the bounded recent window described in each agent's retrieval scope (last 4-6
cycles for `goal-drift-tracker`/`slo-risk-tracker`/`change-impact-synthesizer`; exactly the
two entries bracketing a boundary for `model-boundary-interpreter`; the latest entry per
company for `portfolio-rollup-writer`; no trend data at all for
`policy-compliance-checker`, which instead gets one company-scoped and one shared policy
search per incident). `groundedness-checker` is the narrowest case of all: no tool calls
whatsoever — just the two excerpts (generated output, retrieved source) pushed to it directly,
nothing else fetched because nothing else bears on the one question it answers. Assembled
fresh by `pulse/orchestrator.py` for every invocation, discarded after — an agent never
carries state between invocations. See `.claude/agents/*.md` for each agent's exact
retrieval-scope comment.

## Episodic memory

`pulse/trend_store.py` — the full trend store. Raw, timestamped, append-only, never edited in
place. Every entry records exactly which agent version and model produced it
(`classifying_agent`, `agent_version`, `model`), never re-derived from a live registry lookup
later — that's what makes `pulse/model_boundary.py`'s reproducibility check possible at all:
the record of "what produced this" travels with the data. `pulse/layer_versioning.py` reads
this same episodic record to detect layer-level version changes across cycles — a second
detection path over the identical memory, answering a different question (did the *monitored
system* change) than `model_boundary.py` (did *our own classifier* change).

## Semantic memory

The stable facts fetched via `get_system_charter(company_id)` (CHARTER-tracked companies) and
`get_slo_agreement(company_id)` (SLO-tracked companies) — the behavior boundaries or SLO
thresholds set at launch. Distinct from episodic memory in one crucial way: semantic memory
doesn't change cycle to cycle (the charter a system launched with is fixed), while episodic
memory is exactly the cycle-by-cycle record of how the system's real behavior tracked against
that fixed charter.

## Procedural memory — explicitly NOT present

There is no learned-pattern store anywhere in this system that any agent writes to or reads
from. No "the system has learned that X usually means Y" mechanism exists. This is a
deliberate omission, not a gap: `pulse/risk_scoring.py`'s twelve deterministic rules —
the original four (systemic-flag-spike, model-boundary ambiguity, policy violation,
destructive layer change) plus the eight added for extended monitoring (cost anomaly, context
pressure, user-escalation spike, PII exposure, prompt-injection success, agent hand-off loops,
canary divergence, groundedness failure) — serve the role a procedural-memory system might
otherwise fill — **encoded, inspectable rules instead of learned, opaque ones.** If asked directly why: a procedural-memory system that
quietly reweights its own risk thresholds based on outcomes is exactly the kind of drift this
whole project exists to prevent — an escalation rule that changed itself last cycle for
reasons nobody wrote down is indistinguishable, eighteen months later, from the model-boundary
problem this system already has enough trouble catching. Every threshold in `risk_scoring.py`
(the systemic-spike count, the business-day SLAs in `policy_rules.py`) is a plain constant in
source code, changed only by a human editing a file and committing it — that commit *is* the
procedural-memory update, and it's fully auditable. `pulse/benchmarks.py`'s hand-authored case
suites are the same discipline applied one step earlier: a human-written, versioned check run
*before* activation, not a self-tuning gate.

## The concrete "when to ignore memory" case

`policy-compliance-checker` (`.claude/agents/policy-compliance-checker.md`) deliberately does
**not** call `get_trend_history` at all — only `search_policy` plus the current cycle's
already-computed classification/routing decision. This is the system's clearest example of
choosing *not* to retrieve available memory: pulling episodic trend data into a policy-
compliance judgment would add noise, not signal — the question "does this routing satisfy
policy" doesn't get better answered by knowing a company's incident history three years ago.
Every other agent's retrieval scope is about *bounding* memory; this one is about *excluding*
a whole category of it.
