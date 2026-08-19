# 🛰️ Stack Sentinel

**A multi-agent AI software monitoring system built around one constraint: monitor real
software-system mechanics — layer versions, deployment/change events, and discrete
behavior-boundary incidents — never a smoothed trend line that just relabels a financial KPI.**

[![CI](https://github.com/AnikNicks/stack-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/AnikNicks/stack-sentinel/actions/workflows/ci.yml)
[![Deploy Pages](https://github.com/AnikNicks/stack-sentinel/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/AnikNicks/stack-sentinel/actions/workflows/deploy-pages.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

This project started as `portfolio-pulse`, a PE/private-debt financial-monitoring demo built
around the same deterministic/agentic architecture. This build is a full domain pivot — the
underlying architecture (deterministic core, seven single-shot classifiers, versioned rollback)
carries over unchanged; everything the system actually *monitors* was rebuilt from scratch.

**Live demo:** [stack-sentinel.io](https://aniknicks.github.io/stack-sentinel/) — a static,
read-only preview of the actual operator console (bundled snapshot of one real 10-cycle run;
the write action and the live-LLM Ask panel are disabled, since a public static page can't run
the FastAPI backend behind them) · three monitored-company product demos, each replaying its
own real cycle history: [Meridian Concierge](https://aniknicks.github.io/meridian-labs/) ·
[Wayfinder Copilot](https://aniknicks.github.io/wayfinder-ai/) ·
[Cascade Pipeline Agent](https://aniknicks.github.io/cascade-analytics/)

## What this is

Most "AI monitoring" demos prove a model can classify one thing well once. This project asks
a different question: what does it actually take to monitor a multi-agent AI software system
in production, without either (a) needing a human to babysit every classification, or (b)
quietly becoming just another financial-style dashboard with a software label glued on? Four
specific failure modes, each with a real mechanism defending against it:

- **Prompt/version drift.** A prompt edit that looks like an improvement in isolation can
  quietly regress. → A versioned prompt registry with an automated rollback that requires no
  human in the loop, plus a behavioral benchmark gate a human reviews *before* activation.
- **Silent model-boundary shifts.** A "pinned" version can still resolve to a different model
  snapshot underneath it, and the classification can shift for reasons that have nothing to
  do with the monitored system's real behavior. → Deterministic boundary detection,
  unconditionally routed to a human — never auto-resolved, regardless of confidence.
- **Destructive changes with no automated safety net.** A layer-level change with real
  data-loss potential (a schema drop, an unrecoverable credential rotation) must never be
  auto-remediated, no matter how confident the system is. → A dedicated module,
  `pulse/human_approval.py`, whose one function structurally cannot return `action_taken:
  True` — not "a human is in the loop," but "there is no automated path to gate at all."
- **Unreviewed policy misses.** A routing decision can be technically correct and still miss
  the intent of an escalation clause. → A semantic policy check that runs *alongside*
  deterministic literal counting, not instead of it.

The architectural answer to all four is the same: **push everything that can be
deterministic out of the model entirely.** Version management, the trend store, risk scoring,
rollback, layer-change detection, model-boundary detection, and the literal/countable parts
of policy compliance are plain, unit-tested Python with zero LLM involvement. The only places
a model is involved are seven single-shot Claude Code subagents — each invoked once, given a
bounded context, producing one JSON classification. Nothing in this system asks a model to
plan, loop, or decide whether it needs more information; see
[Project architecture](#project-architecture) for why that structurally rules out an entire
category of agent failure mode.

## Core features

- **Deterministic core, fully unit-tested, zero LLM.** Trend store, layer-version detection,
  risk scoring, model-boundary detection, rollback, human-approval gating, incident/replay
  bundles, notification dispatch, benchmark gating, metrics rollups, schema validation, retry
  policy, and audit logging — all plain Python, all tested without a single model call.
- **Six narrow, single-shot subagents — not planners.** Each is invoked once per company per
  cycle (or once per detected boundary), with a hard tool-call cap and a bounded retrieval
  scope stated in its own prompt. See [Project architecture](#project-architecture).
- **A versioned prompt registry with automatic rollback and a pre-activation gate.** Every
  classification is stamped with the exact agent version and model that produced it — never
  re-derived later — which is what makes reproducing an incident from disk actually possible.
  `pulse/benchmarks.py` runs a hand-authored case suite against every new version *before* a
  human is allowed to activate it, alongside the after-the-fact auto-rollback safety net. See
  [`VERSIONING.md`](VERSIONING.md) for three full worked scenarios with real numbers from an
  actual run.
- **Destructive changes are structurally never auto-executed.** Not a policy, a guarantee:
  `pulse/human_approval.gate_destructive_action` has no branch that returns `action_taken:
  True`. See `VERSIONING.md`'s worked scenario 3 for a real incident that reached this gate.
- **A live operator console, not a static export.** `dashboard/api` (FastAPI) +
  `dashboard/web` (React) — System / Ask / Companies / Incidents, including the one real
  write action in the whole system, approving or rejecting a pending destructive-change (or
  other high-risk) incident.
- **Three illustrative product demos.** `companies/*` — one React app per monitored company,
  each dramatizing that company's real charter boundary or SLO in a clickable product
  surface, plus a data-driven replay of its real 10-cycle monitoring history. Read-only:
  nothing here ever feeds back into the monitoring pipeline.

## Live demo

Three companies, one 10-sprint-cycle run (`2025-S01` → `2025-S10`), each carrying a different
real story:

| Company | Track | Tracked against | What happened |
|---|---|---|---|
| Meridian Labs — "Meridian Concierge" | CHARTER | Agent behavior boundaries (refund approval, shipping-address confirmation) | A prompt regression misread a benign audit-log artifact as attributable, alongside Wayfinder in the same cycle — caught by the systemic-flag-spike rule and **auto-rolled-back**, no human involved (`INC-0007`). Separately, its own `escalation-agent` gets caught in a real hand-off loop with `resolution-agent`, high-risk-tiered and held for human approval (`INC-0010`) |
| Wayfinder AI — "Wayfinder Copilot" | CHARTER | Agent behavior boundaries (non-refundable-booking confirmation) | Same prompt version, different underlying model snapshot, one cycle apart — a genuine **model-boundary event**, unconditionally routed to human review (`INC-0013`). A real card-like number surfaces in a booking confirmation, flagged as a **PII exposure** (`INC-0006`) |
| Cascade Analytics — "Cascade Pipeline Agent" | SLO | Monthly error-budget consumption | Two consecutive warning-threshold cycles trip the RRB reporting clause (real dispatch); a proposed non-reversible schema drop is flagged and **blocked pending human approval** (`INC-0011`), later explicitly approved. A schema-inference summary is caught **fabricating** a field its own retrieved source never defines (`INC-0014`, `groundedness-checker`) |

### Screenshots

Every screenshot below is of the actual live static preview (`stack-sentinel.io`) or the actual
company demo app — not a mockup, and not the stale early-build UI a README image can quietly
drift into: these were re-captured this session against the current 4-section console (System /
Ask / Companies / Incidents) and its real 14-incident dataset.

| System Overview | Companies Detail |
|:---:|:---:|
| <img src="docs/screenshots/01-overview.jpg" width="480" alt="Portfolio snapshot: 3 companies monitored, 1 open incident, 2 auto-resolved, 14 total, with per-company trend sparklines"> | <img src="docs/screenshots/03-company-detail.jpg" width="480" alt="Meridian Labs: charter boundaries, internal agents with real rollback status, and policy clauses"> |
| *Portfolio-wide snapshot — live incident counts and a 6-cycle trend sparkline per company.* | *One company's full detail: charter boundaries, internal agents (note `intake-triage-agent`'s real `rolled back` status), and policy.* |

| Incidents Queue | Company Product Demo |
|:---:|:---:|
| <img src="docs/screenshots/02-incidents.jpg" width="480" alt="All 14 real incidents across every finding kind, risk tier, routing decision, and status"> | <img src="docs/screenshots/04-cascade-product-demo.jpg" width="480" alt="Cascade Pipeline Agent product demo: error-budget gauge and the blocked destructive migration"> |
| *All 14 incidents on record — every finding kind, risk tier, routing decision, and status, in one table.* | *Cascade's illustrative product demo — the same blocked destructive migration from the story above, dramatized in-product.* |

## Project architecture

<p align="center"><img src="docs/screenshots/stack-sentinel-architecture.png" alt="Stack Sentinel request-to-resolution flow: a per-cycle data snapshot flows into the zero-LLM deterministic core (layer versioning, model-boundary detection, risk scoring, incidents, human approval, policy rules, PII/injection/loop/canary detection, company registry + rollback), through the orchestrator's single shared _route_finding() incident lifecycle, across the deterministic/agentic boundary into the seven single-shot subagents, through human_approval.py's destructive-action gate that structurally cannot auto-execute, out through pulse/notifications.py — the only module allowed to call real Gmail/Jira/Confluence/Slack — and finally into two read-only UI consumers, the operator console and the company demo apps" width="820"></p>

*Full request-to-resolution flow, one layer at a time — the data source of truth, the
zero-LLM deterministic core, the orchestrator's shared incident lifecycle, the
deterministic/agentic boundary, the human-approval gate, real external dispatch, and the two
read-only UI consumers.*

Seven subagents, each a single-shot classifier with a retrieval scope sized to exactly what its
judgment needs — not "always retrieve everything":

| Agent | Retrieval scope | Invoked | Produces |
|---|---|---|---|
| `goal-drift-tracker` | Charter boundaries, current system metrics, bounded trend history | Once per CHARTER company per cycle | Raw charter read (`on_charter` / `watch` / `drifted`) |
| `slo-risk-tracker` | SLO agreement, current system metrics, bounded trend history | Once per SLO company per cycle | Trajectory commentary only — the `compliant`/`warning`/`breach` label itself is pure Python |
| `change-impact-synthesizer` | Last 4–6 cycles of trend history | Once per company per cycle, CHARTER and SLO alike | Attributable-vs-noise verdict — the causal-attribution gate on CHARTER's final classification |
| `model-boundary-interpreter` | Exactly the two trend entries bracketing a detected boundary | Only when `model_boundary.py` already deterministically found one | Genuine-change vs. model-interpretation-noise judgment |
| `portfolio-rollup-writer` | Latest entry per company, portfolio-wide | Once per reporting cycle | One cross-company report |
| `policy-compliance-checker` | Policy corpus (company-scoped + shared) only — **deliberately no trend history at all** | Once per incident's routing decision, per company named on it | Borderline "intent of the clause" judgment |
| `groundedness-checker` | **Zero tool calls** — just the generated output excerpt and its source excerpt, pushed directly | Once per `groundedness_check` event | `grounded` / `unsupported` / `fabricated` judgment |

That last row is the clearest example in this system of *excluding* memory on purpose, not
just bounding it — pulling episodic trend data into a policy-compliance judgment adds noise,
not signal, to the question "does this routing satisfy policy." Full memory-model mapping
(working / episodic / semantic / and the deliberate absence of procedural memory) is in
[`MEMORY.md`](MEMORY.md).

Nothing here asks a subagent to plan, loop, or request more context — each has exactly one
turn, a hard cap on tool calls stated in its own prompt, and one required JSON output shape.
See [`CLAUDE.md`](CLAUDE.md) for the full reasoning, and [`SECURITY.md`](SECURITY.md) for a
real audit against known agentic-tool risk classes (prompt injection, privilege escalation,
exfiltration, hallucinated tool calls, runaway cost), each claim cited to a real
file:function.

## Guardrails

Stated honestly — what's enforced by code versus what's prompt-level discipline.

**Enforced in code:**
- Every trend entry is stamped with the exact `classifying_agent` / `agent_version` / `model`
  that produced it, never re-derived from a later registry lookup — the record of "what
  produced this" travels with the data, which is what makes reproducing an incident from disk
  possible.
- `pulse/human_approval.py` contains exactly one function, and it has no branch that returns
  `action_taken: True` — destructive layer changes cannot be auto-executed, structurally, not
  by policy.
- `pulse/soft_fix.py` contains exactly one function and nothing else, by design — reverting to
  a previously-live version is the only automated *remediation* action anywhere in this system.
- Model-boundary findings route to `human_review` unconditionally — no code path lets one
  auto-resolve, regardless of confidence.
- Missing or malformed agent output gets exactly one defined fallback (`assessment_failed`),
  written once — never retried indefinitely, never silently skipped.
- No agent that reads untrusted content (system metrics, policy text, trend history) also
  holds a write-capable tool in the same turn. `append_trend_entry` and the real
  Gmail/Jira/Confluence/Slack tools are called only by the orchestration layer, using an
  agent's *validated structured output* — never raw agent text.
- New agent-prompt versions run through `pulse/benchmarks.py`'s hand-authored case suite
  *before* a human is allowed to activate them — a second gate alongside the after-the-fact
  auto-rollback safety net.

**Convention-level (prompt discipline, not sandboxed):**
- Every agent's prompt states a hard cap on tool calls per invocation.
- Each agent's tool definitions carry a one-sentence retrieval-scope comment sized to its
  actual judgment — see the table above.
- No secret is ever visible to, or passed through, the assistant. Docker MCP credentials live
  only in the OS keychain (`docker mcp secret set`); the OpenAI key (used only by
  `dashboard/api`'s optional `/ask` endpoint) lives only in a gitignored `.env`, read
  exclusively by server-side code that never logs or echoes it.

## Tech stack

| Layer | Choice |
|---|---|
| Agents & orchestration | Claude Code subagents (`.claude/agents/*.md`) + a plain-Python orchestrator — no agent framework |
| Deterministic core | Python 3.12, zero LLM calls (`pulse/*.py`) |
| MCP server | `mcp` SDK v2.0.0 (`mcp_server/server.py` + `tools_impl.py`), 7 tools, schema-verified |
| Vector store | chromadb, default local embedding model — no external API key needed |
| Real external connectors | Docker MCP Toolkit (`gmail-mcp`, `atlassian`, `slack`), driven by a real MCP client in `pulse/notifications.py` — dry-run by default; `--live` verified end-to-end against real accounts (see [Engineering notes](#engineering-notes-going-live)) |
| Live console | FastAPI (`dashboard/api`) + Vite/React (`dashboard/web`) — local-only by design (real write action, no auth); a static read-only preview build ships to Pages instead |
| Optional live Q&A | OpenAI Chat Completions (`gpt-4o-mini`, `temperature=0`), via `dashboard/api`'s `POST /ask` — the one non-Anthropic model call anywhere in this repo |
| Company demo apps | Vite/React, static builds, no backend — `companies/*`, each its own repo + Pages site |
| Tests | pytest + a framework-free fallback (`tests/run_tests.py`) — 127 + 57 passing |
| CI/CD | GitHub Actions — `ci.yml` (pytest + both frontend builds) and `deploy-pages.yml`, both required-green on every push to `main` |

## Repository structure

```
.claude/agents/           seven subagent definitions — single-shot classifiers, not planners
pulse/                    deterministic core: trend store, layer versioning, risk scoring, rollback, human approval, notifications
mcp_server/               MCP server (server.py) + real tool implementations (tools_impl.py)
registry/<agent>/         versioned prompt bundles (v1.yaml, v2.yaml, ...) + active.yaml
policy/                   monitoring_escalation_policy.md + chromadb persistence (gitignored)
data/                     portfolio_companies.json, layer_metrics/, trend_store/, incidents/
scripts/                  seed_registry.py, simulate_production_run.py, export_company_fixtures.py, export_dashboard_snapshot.py, ...
dashboard/                api/ (FastAPI) + web/ (React) — the live operator console, with a static-preview build mode for Pages
companies/                meridian-labs/, wayfinder-ai/, cascade-analytics/ — 3 product demo apps
tests/                    pytest suite + framework-free run_tests.py
docs/screenshots/         README screenshots + the architecture diagram
CLAUDE.md, MEMORY.md, VERSIONING.md, SECURITY.md   architecture, memory-model, rollback, and security docs
```

## Getting started

```bash
# 1. Install
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt         # macOS/Linux

# 2. Seed the registry + policy corpus (idempotent, safe to re-run)
.venv\Scripts\python scripts\seed_registry.py
.venv\Scripts\python -c "from pulse import vector_store; vector_store.ingest_policy_corpus()"

# 3. Run the simulation — 10 sprint cycles x 3 companies, fresh state
.venv\Scripts\python scripts\simulate_production_run.py --reset
#   add --live to fire real Gmail/Slack/Jira/Confluence notifications — requires your own
#   Docker MCP Toolkit profile and credentials, never checked into this repo (see .env.example)

# 4. Tests
.venv\Scripts\python -m pytest tests\ -v

# 5. Live console
.venv\Scripts\python -m uvicorn dashboard.api.main:app --reload   # terminal 1
cd dashboard\web && npm install && npm run dev                    # terminal 2, then open http://localhost:5173

# 6. Company demo apps (each independent, its own terminal)
cd companies\meridian-labs && npm install && npm run dev
cd companies\wayfinder-ai && npm install && npm run dev
cd companies\cascade-analytics && npm install && npm run dev

# 7. Static dashboard preview (optional) — what actually ships to Pages: reads a bundled
#    read-only data snapshot instead of a live backend, decision/Ask calls disabled
cd dashboard\web
.venv\Scripts\python ..\..\scripts\export_dashboard_snapshot.py
npm install
$env:VITE_STATIC_MODE="true"; npm run build   # PowerShell; VITE_STATIC_MODE=true npm run build on macOS/Linux
```

## Engineering notes: going live

Getting `--live` notification delivery and the Pages deploy actually working surfaced two real
bugs that never showed up in local dry-run testing or CI — both root-caused, fixed, and
verified against the real live systems, not patched blind:

- **Wrong tool names and parameters against the real Atlassian remote MCP server.**
  `pulse/notifications.py` called `jira_create_issue` / `confluence_create_page` with
  `project_key` / `space_key` — names invented against the *shape* of the API, never checked
  against the real server. The actual Atlassian remote MCP exposes `createJiraIssue` /
  `createConfluencePage`, requires a `cloudId` that wasn't configured anywhere, and Confluence
  needs the space's numeric ID, not its human-readable key. Found by actually running `--live`
  and reading the error, not by inspection. Fixed with a schema-verified tool call, a new
  `PULSE_ATLASSIAN_CLOUD_ID`, and a cached space-key→ID resolver — verified with a real
  `--reset --live` run: **34/34 dispatches sent** (15 email, 14 Slack, 1 Jira, 4 Confluence),
  0 errors.
- **A redundant, incorrectly base-pathed Pages build.** The original `deploy-pages.yml` also
  rebuilt the 3 company apps a second time under `stack-sentinel.io/<company>/`, with no
  `--base` flag — which would have emitted root-relative asset URLs colliding with the new
  dashboard's own assets at the site root. Each company app already has its own correctly
  base-pathed standalone Pages site; the redundant nested copy was removed, and the dashboard
  build gained an explicit `--base=/stack-sentinel/`. Verified live: `curl` confirms the old
  nested paths now 404 and the dashboard's own assets resolve correctly.

The common thread: both were only catchable by actually running the live path end-to-end
against the real external systems — no amount of local dry-run testing or green CI would have
caught either one, because dry-run mode by design never calls the real tool, and CI never
deploys to Pages and then fetches the result back.

## Roadmap

- The seven subagents are spec-verified (frontmatter, retrieval scopes, tool caps, JSON
  contracts) but have never been invoked over a live `claude` CLI round-trip in this build —
  `simulate_production_run.py` feeds scripted stand-in classifications into the real
  orchestrator/risk-scoring/notification pipeline; only the classification *text* is
  scripted, every failure path, idempotency check, layer-change detection, and routing
  decision downstream of it is real.
- Run against more than 10 cycles and more than 3 companies to see how the causal-attribution
  gate and rollback mechanism hold up at real portfolio scale.
- Hosting `dashboard/api` itself publicly (a fully live, not just preview, console) was
  considered and declined — it has a real write action and no auth in front of it, so the
  static read-only preview is the deliberate choice, not a placeholder for a later step.

## License

[MIT](LICENSE)
