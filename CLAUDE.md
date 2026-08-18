# CLAUDE.md — Stack Sentinel

Guidance for any Claude Code session (or any agent) working in this repository.

## What this project is

Stack Sentinel is a monitoring system for multi-agent AI software companies, designed to run
bi-weekly over a multi-year production lifetime. Its defining property is TIME: the value is
in the longitudinal trend record, not any single assessment. Every architectural choice in
this repo exists to protect that trend record from the failure modes unique to a long-horizon
LLM system — prompt/version drift, model upgrades silently changing interpretation underneath
a "pinned" version, and unreviewed policy misses. What it actually monitors is deliberately
**not** a smoothed metric: each cycle's record is layer-level version changes, operational
health, and discrete behavior-boundary incidents — never a single scalar trending up or down.
See `README.md` for the full picture, `MEMORY.md` for how this system's memory maps to the
standard working/episodic/semantic/procedural taxonomy, `VERSIONING.md` for the rollback
mechanism, and `SECURITY.md` for the agentic-tool risk-class audit.

## The deterministic/agentic boundary (non-negotiable)

Version management, the trend store, layer-change detection, model-boundary detection, risk
scoring, idempotency, rollback, and the literal/countable parts of policy compliance are
**plain, deterministic Python with zero LLM involvement**. A monitoring system whose own
logic is unpredictable defeats its purpose. All of that code lives in `pulse/` and is fully
unit-tested without any model calls. The only places an LLM (a Claude Code subagent) is
involved are the six single-shot classifiers in `.claude/agents/` — and even there, their job
is narrow classification, not open-ended reasoning.

**One further non-negotiable specific to this domain:** destructive or irreversible changes to
a monitored system's layers (a database schema drop, an unrecoverable credential rotation,
anything with real data-loss potential) are **never** auto-remediated by any part of this
system, regardless of confidence. `pulse/layer_versioning.py` classifies a change_event's
reversibility as a literal, provided fact; `pulse/risk_scoring.py` routes any non-reversible
change to `pending_human_approval` unconditionally; `pulse/human_approval.py` is the one
module that formally refuses to act — `gate_destructive_action()` always returns
`action_taken: False`. Only a human, via `pulse.incidents.record_approval_decision()`, can
authorize what happens next, and even that recording performs no action itself.

## Design choice: every agent is a single-shot classifier, not a planner

Every agent in this project is invoked once per company per cycle (or once per detected
boundary, for `model-boundary-interpreter`), given a bounded, pre-assembled context, and
produces exactly one JSON classification. This is a **deliberate design choice**, not an
oversight: nothing in this system asks an agent to plan, loop, explore, or decide whether it
needs more information. The orchestrator assembles the context; the agent classifies; the
orchestrator validates and records the result. There is no step where an agent chooses its own
next action.

**Why this project doesn't need chain-of-thought/tree-of-thought/loop-detection machinery the
way a multi-step planning agent would:** that machinery exists elsewhere to catch a planner
that has gone off the rails after many self-directed steps — re-exploring the same ground,
escalating its own scope, or spinning on an ambiguous goal. A single-shot classifier
structurally cannot do any of that: it has exactly one turn, a fixed set of allowed tool
calls stated as a hard cap in its own prompt, and one required output shape. The failure mode
loop-detection exists to catch is prevented by the architecture itself, not detected after the
fact.

That said, guardrails still exist, because "the agent shouldn't need to loop" is not the same
guarantee as "the agent cannot misbehave":
- Every agent's prompt states a hard cap on tool calls per invocation (e.g.
  `change-impact-synthesizer` may call `get_trend_history` at most once).
- Every agent's prompt is action-biased: given the data provided, produce a classification —
  do not request more context, do not defer the decision.
- If an agent's output is missing, malformed, or a tool call errors, the orchestrator applies
  exactly ONE default: write an `assessment_failed` entry with the raw error preserved. Never
  retried indefinitely, never silently skipped.
- No agent that reads external content (system metrics, policy text, trend history — all
  untrusted, all treated as data never as instructions) also holds a write-capable tool in the
  same turn. `append_trend_entry` and the real Gmail/Jira/Confluence/Slack tools are called
  only by the orchestration layer (`pulse/orchestrator.py`, `pulse/notifications.py`), using an
  agent's own validated structured output — never raw MCP response text, and never called by
  an agent directly.

## Retrieval scopes are stated per agent, not "always retrieve everything"

Each agent's tool definitions carry a one-sentence retrieval-scope comment describing exactly
what it's allowed to pull, sized to what its judgment actually needs:
- `goal-drift-tracker`, `slo-risk-tracker`, `change-impact-synthesizer`: a bounded recent
  window (last 4-6 cycles) of trend history — enough to tell an isolated incident from an
  emerging pattern, without unbounded history diluting that judgment with stale data.
- `model-boundary-interpreter`: only the two specific trend entries bracketing the detected
  boundary — it is judging one before/after pair, not the whole history.
- `portfolio-rollup-writer`: the latest entry per company across the portfolio — a
  point-in-time summary, not a trend analysis.
- `policy-compliance-checker`: deliberately does **not** retrieve trend history at all — see
  `MEMORY.md` for why this is the concrete "when to ignore memory" case in this system.

## What's real vs. scripted in this repo

Every deterministic module in `pulse/` is real, executed code with real tests. The MCP server
and the six subagents are complete, spec-correct artifacts, but no live `claude` CLI session
was available to invoke the agents themselves during this build — so
`scripts/simulate_production_run.py` feeds *scripted* classification outputs (explicitly
labeled as stand-ins for what those agents would return) into the *real*
orchestrator/risk-scoring/incident/notification pipeline. Only the agents' classification text
is scripted; every failure path, idempotency check, layer-change detection, rollback, and
routing decision in the simulation is produced by the real deterministic code acting on that
scripted input, not narrated. See `README.md` for the full "implemented vs.
designed-but-not-live-tested" breakdown.

## Two web UIs, both read-only consumers of the same `data/` files

`dashboard/api` + `dashboard/web` are Stack Sentinel's own live operator console — the one
place in this whole system with a real write action (approving/rejecting a
`pending_human_approval` incident). `companies/*` are three separate, illustrative product
demos for the monitored companies themselves. Neither ever feeds data back into the monitoring
pipeline: `data/layer_metrics/*.json` stays the sole source of truth the classifiers and
orchestrator run against, so the scripted simulation stays reproducible regardless of what a
viewer clicks in either UI.
