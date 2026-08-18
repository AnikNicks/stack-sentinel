# CLAUDE.md — Stack Sentinel

Guidance for any Claude Code session (or any agent) working in this repository.

## What this project is

Stack Sentinel is a monitoring system for PE/private-debt portfolio companies, designed to
run quarterly over a multi-year hold. Its defining property is TIME: the value is in the
longitudinal trend record, not any single assessment. Every architectural choice in this repo
exists to protect that trend record from the failure modes unique to a long-horizon LLM
system — prompt/version drift, model upgrades silently changing interpretation underneath a
"pinned" version, and unreviewed policy misses. See `README.md` for the full picture,
`MEMORY.md` for how this system's memory maps to the standard working/episodic/semantic/
procedural taxonomy, and `VERSIONING.md` for the rollback mechanism.

## The deterministic/agentic boundary (non-negotiable)

Version management, the trend store, model-boundary detection, risk scoring, idempotency,
rollback, and the literal/countable parts of policy compliance are **plain, deterministic
Python with zero LLM involvement**. A monitoring system whose own logic is unpredictable
defeats its purpose. All of that code lives in `pulse/` and is fully unit-tested without any
model calls. The only places an LLM (a Claude Code subagent) is involved are the six
single-shot classifiers in `.claude/agents/` — and even there, their job is narrow
classification, not open-ended reasoning.

## Design choice: every agent is a single-shot classifier, not a planner

Every agent in this project is invoked once per company per quarter (or once per detected
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
  `trend-synthesizer` may call `get_trend_history` at most once).
- Every agent's prompt is action-biased: given the data provided, produce a classification —
  do not request more context, do not defer the decision.
- If an agent's output is missing, malformed, or a tool call errors, the orchestrator applies
  exactly ONE default: write an `assessment_failed` entry with the raw error preserved. Never
  retried indefinitely, never silently skipped.
- No agent that reads external content (financials, policy text, trend history — all
  untrusted, all treated as data never as instructions) also holds a write-capable tool in the
  same turn. `append_trend_entry` and the real Gmail/Jira/Confluence/Slack tools are called
  only by the orchestration layer (`pulse/orchestrator.py`, `pulse/notifications.py`), using an
  agent's own validated structured output — never raw MCP response text, and never called by
  an agent directly.

## Retrieval scopes are stated per agent, not "always retrieve everything"

Each agent's tool definitions carry a one-sentence retrieval-scope comment describing exactly
what it's allowed to pull, sized to what its judgment actually needs:
- `pe-thesis-tracker`, `pd-covenant-tracker`, `trend-synthesizer`: a bounded recent window
  (last 4-6 quarters) of trend history — enough to tell genuine inflection from noise, without
  unbounded history diluting that judgment with stale data.
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
is scripted; every failure path, idempotency check, rollback, and routing decision in the
simulation is produced by the real deterministic code acting on that scripted input, not
narrated. See `README.md` for the full "implemented vs. designed-but-not-live-tested"
breakdown.
