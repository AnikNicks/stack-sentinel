# Stack Sentinel — Build Progress

This file is a living document, not a log — it is rewritten as work progresses so it always
reflects the current true state of the repo. A future session should be able to read this
file alone and know what's built, what's tested, what's left, and where.

## Status

**Build complete AND genuinely live.** All 11 phases done, all real, all verified for real.
On 2026-08-13, `scripts/simulate_production_run.py --reset --live` was run for real against
the fully-credentialed `portfolio-pulse` Docker MCP profile: **all 14 notification dispatches
came back `live: true, status: "sent"`, zero errors**, across email, Slack, Jira, and
Confluence — confirmed independently by reading the real Gmail inbox back
(`[Stack Sentinel] ACTION: ...` emails present). See "Live-readiness check" below for the
full history, including a real Windows subprocess-env bug found and fixed along the way
(`pulse/notifications.py`'s `_windows_docker_cli_plugin_env`). Nothing about this remains
theoretical.

## Done

- **Phase 0 — Scaffolding:** project root, `.venv` (pyyaml/numpy/pytest/mcp/chromadb all
  installed and working — chromadb's default ONNX embedding model confirmed working
  end-to-end, so the TF-IDF fallback is **not needed**), directory layout, `.gitignore`,
  `CLAUDE.md` (single-shot design rationale).
- **Phase 1 — `pulse/` deterministic core:** all 11 modules written and smoke-tested for
  real (trend_store idempotency, registry+soft_fix rollback, model_boundary's 3 boundary
  kinds, risk_scoring's 3 rules incl. single-flag-no-spike, policy_rules counting/business
  days, incidents create/review/stale-escalate, schema_validator, audit_log redaction,
  retry backoff+permanent-no-retry — all asserted, not just imported).
- **Phase 2 — data:** `policy/monitoring_escalation_policy.md` written and ingested into
  chromadb — semantic retrieval verified on paraphrased queries (e.g. "lots of companies
  suddenly flagged at once" correctly matches the "Systemic anomalies" clause, not a
  keyword match). `data/portfolio_companies.json` + 8-quarter `data/financials/*.json` for
  all 3 companies authored with the full 5-scenario narrative baked in (see Key decisions).
  Registry version bundles registered via the real `pulse.registry.register_new_version()`
  (`scripts/seed_registry.py`, re-runnable/idempotent) — nothing activated yet; activation
  happens live in the simulation.
- **Phase 3 — MCP server + agents:** `mcp_server/server.py` (real `mcp` SDK `MCPServer`,
  all 7 tools registered and schema-verified via `scripts/verify_mcp_server.py`) +
  `mcp_server/tools_impl.py` (real implementations, explicit `caller` context, PermanentError
  on unknown company / wrong relationship-type). All 6 `.claude/agents/*.md` written with
  valid frontmatter, retrieval scopes, tool-call caps, JSON contracts.
- **Phase 4 — `pulse/orchestrator.py`:** combines pe-thesis-tracker + trend-synthesizer
  (trend-synthesizer as noise-filter gate — see Key decisions) for PE, deterministic
  covenant math + pd-covenant-tracker trajectory commentary for PD, schema-validates agent
  output before writing, `assessment_failed` default on bad/missing output,
  `run_portfolio_quarter` for cross-company systemic-spike + model-boundary handling.
  Import-tested; full behavioral proof comes from the Phase 6 run + Phase 8 tests.
- **Phase 5 — real external connectors:** `pulse/notifications.py` is a real MCP *client*
  (spawns `docker mcp gateway run --profile portfolio-pulse` via the `mcp` SDK's own client,
  not Claude Code's tool-calling) with dry-run-by-default + `enable_live_mode()`. Docker side
  is fully set up: new isolated `portfolio-pulse` profile created (gmail-mcp + atlassian +
  slack), Gmail address configured, project-scoped `.mcp.json` entry registered (no secrets
  in it — safe to commit). **Blocked on user-provided credentials** (Gmail app password,
  Slack bot token + channel id, Atlassian API token + project/space keys) — checklist handed
  to the user with exact `docker mcp secret set` / `docker mcp profile config` commands to
  run themselves so secrets never pass through the assistant. Until those are set,
  `--live` will fail loudly (`NotificationConfigError` / real call error) rather than
  silently pretending to send — dry-run remains the default and is what the rest of the
  build proceeds with.

- **Phase 6 — simulation:** `scripts/simulate_production_run.py --reset` runs clean, all 5
  scenarios verified from real output: legitimate v1→v2 improvement, v2→v3 regression
  misflagging Northwind+Solace in 2026-Q1 → real auto-rollback to v2 (`active.yaml` shows
  `activated_by: pulse-auto-rollback`), Solace's genuine model-boundary in 2026-Q3 (same
  version v2, model string changed) → human review → confirmed model noise, Ferrous Point's
  genuine 2-consecutive-warning covenant issue in 2026-Q2/Q3 → Credit Committee clause fires
  — all real risk_scoring/incidents/registry decisions, not narrated. **Bug found and fixed
  during this run**: the systemic-flag-spike check originally counted ANY flagged company
  including PD covenant warnings, which caused a false spike in 2026-Q3 when Ferrous Point's
  genuine warning coincided with Solace's model-boundary flag. Fixed by scoping the spike
  count to `classifying_agent == "trend-synthesizer"` only in `orchestrator.py` — PD's
  deterministic covenant math can never be evidence of an agent-version regression. Also
  fixed: Solace's model_override needed to persist forward (Q3→Q4) to avoid a spurious
  second boundary. 5 fault-injection drills + the live idempotency double-call all pass for
  real inside the same run.
- **Phase 7:** `investigate_incident.py` and `reproducibility_check.py` both run against the
  real INC-0002 bundle and produce real output (see PRODUCTION_READINESS_REPORT.md).
- **Phase 8 — tests:** 31/31 pytest passed, 21/21 framework-free `run_tests.py` passed
  (isolated via monkeypatch/tempfile, never touch real simulation data).
- **Phase 9 — docs:** README/MEMORY/VERSIONING/PRODUCTION_READINESS_REPORT all written,
  citing real numbers from this run.
- **Phase 10 — dashboard:** `dashboard/dashboard.html` built (dark/light theme, real SVG
  trend charts, incident/notification logs, deterministic grounded Q&A — live-LLM chat was
  requested but is **not possible**: checked the actual Artifacts runtime contract and only
  `downloads`/`mcp` capabilities exist, no free-form completion capability, so pivoted to the
  originally-recommended deterministic engine, told to the user directly). Rendered in Chrome
  via a local http.server preview — found and fixed a real chart-overflow bug (grid item
  needed `min-width:0`) and a missing-charset mojibake bug before publishing. Published:
  https://claude.ai/code/artifact/dec7fab1-0de5-45a1-a8da-a139c0e16bec

## In progress

Nothing — build complete.

## Live-readiness check (2026-08-12)

Verified for real against the actual Docker MCP Toolkit on this machine (`docker mcp profile
show portfolio-pulse`, `docker mcp secret ls`, `docker mcp gateway run --profile
portfolio-pulse --dry-run`) — not re-narrated from the earlier build session. This is the
current, authoritative status; treat anything in Phase 5 above as historical context only.

**Docker / profile:** Docker Desktop MCP Toolkit is up (`v0.43.3`). The `portfolio-pulse`
profile exists, isolated from `anik` and `portfolio-ops-copilot` as designed, and still wires
exactly the 3 servers it should (`gmail-mcp`, `atlassian`, `slack`).

**Gmail — nearly ready:** `email_address: claudecodenotification@gmail.com` is set on the
profile, and a `gmail-mcp.email_password` secret already exists in the OS keychain. Value
unverified (secrets aren't readable), but both pieces gmail-mcp needs are present.

**Atlassian — not configured:** no `confluence`/`jira` config block on the profile at all
(needs at least `url`, ideally `username`, for each — both channels are actually used:
`confluence` for off-thesis deal-partner review + Credit Committee, `jira` for Credit
Committee). No `atlassian.confluence.api_token` / `atlassian.jira.api_token` secret set.

**Slack — not configured:** profile is missing `slack.team_id` (required) and has no
`slack.channel_ids`. No `slack.bot_token` secret set.

**Gateway currently won't start at all:** `docker mcp gateway run --profile portfolio-pulse
--dry-run` fails validation on `slack.team_id` before even getting to check Atlassian —
confirms the whole gateway is one unit: because `pulse/notifications.py` spawns the gateway
with `--profile portfolio-pulse` (not per-server), **Gmail can't go live either until Slack
and Atlassian are both valid too**, even though Gmail's own two pieces are ready. This matches
what Phase 5/Verification #9 already demonstrated (`--live` against the uncredentialed profile
failed loudly on all 14 sends, never silently "sent") — that finding still holds, just
confirmed again independently today.

**Separate from the Docker profile:** `pulse/notifications.py` also reads plain (non-secret)
env vars at run time for the target IDs — `PULSE_SLACK_CHANNEL_ID`, `PULSE_JIRA_PROJECT_KEY`,
`PULSE_CONFLUENCE_SPACE_KEY` (Gmail's `PULSE_EMAIL_ADDRESS` already defaults correctly). These
aren't in the Docker profile at all and must be set in the shell before `--live` runs.

### Exact remaining steps (user-run only — secrets never pass through the assistant, by design)

```
# Atlassian (non-secret config)
docker mcp profile config portfolio-pulse --set atlassian.confluence.url=https://<your-site>.atlassian.net/wiki --set atlassian.confluence.username=<you@example.com> --set atlassian.jira.url=https://<your-site>.atlassian.net --set atlassian.jira.username=<you@example.com>

# Atlassian secrets (API token from id.atlassian.com — same token usually works for both)
echo <token> | docker mcp secret set atlassian.confluence.api_token
echo <token> | docker mcp secret set atlassian.jira.api_token

# Slack (non-secret config)
docker mcp profile config portfolio-pulse --set slack.team_id=<T0XXXXXXX> --set slack.channel_ids=<C0XXXXXXX>

# Slack secret (bot token, starts xoxb-)
echo <token> | docker mcp secret set slack.bot_token

# Verify the whole profile validates
docker mcp gateway run --profile portfolio-pulse --dry-run

# Then, before running --live, set the plain (non-secret) target-id env vars in the same shell:
$env:PULSE_SLACK_CHANNEL_ID = "<C0XXXXXXX>"
$env:PULSE_JIRA_PROJECT_KEY = "<PROJECT_KEY>"
$env:PULSE_CONFLUENCE_SPACE_KEY = "<SPACE_KEY>"
.venv\Scripts\python.exe scripts\simulate_production_run.py --reset --live
```

## Live-readiness check, part 2 (2026-08-13)

All Docker-side config/secrets from the checklist above are now set. Re-verified for real:

- `docker mcp gateway run --profile portfolio-pulse --dry-run` **passes clean** — all 3
  servers start and list tools (slack: 8, gmail-mcp: 3, atlassian: 80).
- **Atlassian — confirmed working with a real read-only call**: `jira_get_all_projects`
  returned the real site's projects — the intended one is key **`KAN`** (name
  "portfolio-pulse"; the other, `SAM1`, is Atlassian's unrelated example project, ignore it).
  `confluence_search` returned real pages, all under space key **`SD`** (the default
  "Software Development" template space — no dedicated space was ever created, so this is the
  one to use).
- **Slack — bot token authenticates** (`slack_list_channels` → `{"ok":true}`), but returned
  zero channels, which usually means the bot hasn't been added as a member anywhere yet.
  Posting to the configured `C0BPX656HB4` may still fail until the bot is invited to that
  channel — untested further (a read of that channel's message history was blocked by the
  session's own auto-mode classifier as a privacy-sensitive read, correctly).
- **Gmail — auth is failing.** `listMessages` against the real IMAP server returned
  `Invalid credentials (Failure)`. The `gmail-mcp.email_password` secret is set but wrong (not
  a valid Gmail **App Password**, or IMAP isn't enabled on the account, or 2FA/app-password
  generation wasn't completed). **This blocks `--live` end-to-end**, not just email: the
  `_dispatch_universal_email_if_high_risk` path in `pulse/notifications.py` fires an email
  alongside *every* qualifying incident regardless of which other channel also fired, so a
  broken Gmail credential means every high/critical-risk cycle will still error even if
  Slack/Atlassian are perfect.

**Non-secret target IDs resolved and written to a new, gitignored `.env`** (not `.env.example`
— that stays a template): `PULSE_SLACK_CHANNEL_ID=C0BPX656HB4`, `PULSE_JIRA_PROJECT_KEY=KAN`,
`PULSE_CONFLUENCE_SPACE_KEY=SD`. `scripts/simulate_production_run.py` does not currently load
`.env` automatically (no `python-dotenv` dependency) — export these into the shell, or add
`python-dotenv`, before a real `--live` run.

## Live-readiness check, part 3 (2026-08-13)

Gmail App Password regenerated by the user and reset via `docker mcp secret set
gmail-mcp.email_password`. Re-verified with the same real, read-only `listMessages` call:
**success**, returned 10 real inbox messages. All three channels (Gmail, Atlassian, Slack) now
authenticate against the real services — nothing left blocking a `--live` run on the
credentials/config side.

## Live run, part 4 — a real Windows bug found and fixed, then a real success (2026-08-13)

With the user's explicit go-ahead, ran `scripts/simulate_production_run.py --reset --live`.
**First attempt failed** — every one of the 14 gateway calls errored with a raw Docker CLI
message (`unknown flag: --profile`, printing root `docker` usage). Investigated rather than
retried blindly:

- Root cause: `pulse/notifications.py` spawns `docker mcp gateway run --profile
  portfolio-pulse` through the `mcp` Python SDK's `stdio_client`, which — on Windows only —
  restricts the child process to a small env-var allowlist (`get_default_environment()` in
  `mcp/client/stdio.py`). That allowlist omits `ProgramFiles`, which the Docker CLI needs to
  discover the `mcp` CLI plugin at all (confirmed by reproducing the exact subprocess call
  directly: identical argv, only the env differed — with `ProgramFiles` present, `docker mcp
  --help` correctly showed the MCP Toolkit CLI; without it, `docker` silently fell back to
  generic help, then choked on `--profile` as an unrecognized root flag).
- Second layer, found immediately after fixing the first: the `docker-mcp` Go binary itself
  then panicked (`unable to get 'ProgramData'`) reading Docker Desktop's admin settings — also
  missing from the same allowlist.
- **Fix**: added `pulse/notifications.py::_windows_docker_cli_plugin_env()`, which supplies
  `ProgramFiles`/`ProgramW6432`/`ProgramData` from the real environment into the
  `StdioServerParameters.env` override (merged on top of the SDK's restricted default, per
  `stdio.py`'s own `get_default_environment() | (server.env or {})`), gated to
  `sys.platform == "win32"` so POSIX behavior is untouched. Verified in isolation first (a
  harmless `slack_list_channels` read-only call through the real `_call_gateway_tool` code
  path, before touching anything that sends) — confirmed working end to end — then re-ran the
  full simulation.
- **Second attempt: clean.** All 14 dispatches `live: true, status: "sent"`, 0 errors. Emails
  independently confirmed landed via a real `listMessages` read-back.

This fix is a genuine, minimal correctness fix to already-designed behavior (the live path was
always supposed to work on Windows) — not new scope. No credential ever passed through the
assistant at any point in this investigation; only two harmless read-only calls
(`slack_list_channels`, `listMessages`) were used to verify, before and after the real send.

## Dashboard interactivity + Ask Stack Sentinel expansion (2026-08-13/14)

- **Click-through full detail on every figure**: overview-card metrics, trend-chart points,
  incident rows, and trend-synthesizer version-rail markers all got a hover preview (full,
  untruncated rationale — previously cut at 160/220 chars) plus a click-to-open modal with
  complete structured detail (all metrics that quarter, contributing-assessment breakdown,
  linked incidents, full escalation logs, version changelogs). `dashboard_template.html` only;
  rebuild with `dashboard/build_dashboard.py` after any further template edit.
- **"Ask Stack Sentinel" was never LLM-backed** — it's a deterministic keyword-matcher over
  `data_snapshot.json`, by design (see the now-superseded Phase 10 note above: no free-form
  completion capability exists for a published Artifact, and this repo's own CLAUDE.md rule is
  zero LLM calls outside the six subagents). Its coverage was too narrow, though — expanded it
  with a ~16-term concept glossary (on_thesis/watch/off_thesis, warning/breach, idempotency,
  risk tiers, etc.), portfolio-wide meta questions (counts, lists, summaries), and — the real
  fix for "why doesn't it answer new questions" — a full-text fallback search that scores every
  real record (all trend entries + contributing assessments, all incidents, all registry
  versions) by shared keywords before declining, instead of a flat "no match".
- **Optional live-LLM backend added** (`dashboard/ask_server.py`), by explicit user request and
  their own OpenAI key — this is the one and only non-Anthropic model call anywhere in the
  repo, and it's entirely outside pulse/'s deterministic core and the six Claude subagents.
  Serves the dashboard's static files plus `POST /ask` on one origin (no CORS needed).
  `temperature=0`, grounded by passing the real `data_snapshot.json` as context, a system
  prompt that refuses to answer outside that data and refuses to follow instructions embedded
  in the user's question (prompt-injection guardrail), and PII redaction (email/SSN/card/phone
  patterns) applied to both the outgoing question and the incoming answer. Reads
  `OPENAI_API_KEY` / `PULSE_OPENAI_MODEL` (default `gpt-4o-mini`) from the environment or
  `.env` — never hardcoded, never logged. The dashboard's `runAsk()` tries `/ask` first and
  falls back to the deterministic engine automatically and silently on any failure (not
  running, no key, timeout) — the page works identically whether this backend exists or not.
  Verified: server starts, serves static files, and returns the correct honest error with no
  key configured; PII redaction unit-checked directly; frontend fallback path confirmed live in
  Chrome.

  **Verified live with a real `OPENAI_API_KEY` on 2026-08-14** (key added directly to `.env` by
  the user, never seen by the assistant — the first key pasted in was rejected by OpenAI as
  invalid/wrong-format, caught and reported honestly rather than silently retried; the
  corrected key worked once the server was restarted to pick up the new `.env` value — it only
  loads `.env` at process start, not per-request, worth remembering on any future key
  rotation). Real end-to-end test: an open-ended question the deterministic engine structurally
  cannot answer ("which company has the highest risk right now and why, in your own words?")
  got a correct, data-grounded `gpt-4o-mini` answer (Ferrous Point, 4.3x leverage, 2
  consecutive warning quarters), with the UI honestly labeling it as live-model-answered vs.
  deterministic-fallback. `MAX_ANSWER_TOKENS` raised 400 → 1600 (`PULSE_OPENAI_MAX_TOKENS`) so
  normal answers don't hit the cap; if a response is cut off anyway (stress-tested with a
  deliberate "dump the entire dataset" prompt), that's now surfaced explicitly in the answer
  text rather than silently truncated — same "never silently claim success" discipline as the
  rest of this repo.

## Dashboard data freshness fix (2026-08-14)

The dashboard was showing stale dry-run data: `data_snapshot.json` hadn't been regenerated
after the real `--live` run, so the badge read "DRY-RUN" and the notification table showed all
14 dispatches as dry-run even though `notifications_log.jsonl` on disk already had them as
`live: true, status: "sent"`. Fixed: re-ran `scripts/export_dashboard_data.py` (reads live
`pulse/trend_store`, `incidents`, `registry`, `notifications_log.jsonl` directly — no hand-typed
numbers) and `dashboard/build_dashboard.py`, then confirmed live in Chrome — badge now reads
"LIVE run", table shows real `SENT` chips. Also fixed the one contradictory line this caused in
`PRODUCTION_READINESS_REPORT.md`'s "Notification dispatch" section. `pulse/notifications.py`
now auto-loads `.env` at import (same minimal loader as `ask_server.py`, real env vars still
win) so a future `--live` run picks up the `PULSE_*` target IDs without a manual `export` step
first — closes the "doesn't auto-load `.env`" note from earlier. Full pytest suite (31/31)
re-verified after this change.

## Remaining

Nothing blocking, on any of: `pulse/` core, the Docker MCP live profile, the dashboard, or
`ask_server.py`. One soft, non-blocking note carried forward for awareness only:
- Slack's `slack_list_channels` still reports 0 channel memberships even though
  `slack_post_message` to `C0BPX656HB4` succeeded live — likely a `channels:read` vs
  `chat:write` scope difference, not a functional problem; only matters if channel *listing*
  is ever needed somewhere else in this system.

One external, optional item — not started, needs the user's call: the dashboard published as a
Claude Artifact (linked earlier in this doc) is a static snapshot from before this session's
live run and dashboard-interactivity work, so it's now visibly out of date (still shows
DRY-RUN). Republishing is a "publish externally" action requiring explicit go-ahead each time,
not something to do proactively.

## Key decisions

- **Project root is `New folder\portfolio-pulse\`, not a renamed `New folder`** — the outer
  session's host process holds `New folder` open, so a live rename fails with "used by
  another process" (confirmed, tried twice via PowerShell from the parent). Push to GitHub
  from inside `portfolio-pulse/` as the repo root, or rename `New folder` by hand after this
  session ends.
- Idempotency: `append_trend_entry` no-ops with a log message on duplicate
  `(company_id, quarter)`, does not raise.
- Vector store: real chromadb, default embedding model, confirmed working — no fallback used.
- **PE classification composition:** trend-synthesizer acts as the noise-filter *gate* on
  pe-thesis-tracker's raw thesis read — `final = raw_classification if read=="inflection"
  else "on_thesis"`. This is why a trend-synthesizer regression (stops filtering noise)
  causes false off_thesis calls without pe-thesis-tracker itself changing, and why every PE
  trend entry is stamped with trend-synthesizer's version/model (the versioned engine being
  tracked), with pe-thesis-tracker's raw read preserved in `contributing_assessments`.
- **PD classification is pure covenant math** (`orchestrator.classify_pd_covenant`), never
  an LLM judgment; pd-covenant-tracker only supplies trajectory commentary for the
  rationale. PD entries are stamped with pd-covenant-tracker's version/model (stable
  throughout — Ferrous Point is untouched by the trend-synthesizer regression/rollback and
  model-boundary events by design, so its story stays a clean, isolated signal).
  quarters: fuel-cost noise quarter is 2025-Q2, the v2→v3 regression quarter is 2026-Q1
  (Northwind + Solace misflagged, Ferrous Point uninvolved), the model-boundary quarter is
  2026-Q3 (Solace only), Ferrous Point's 2-consecutive-warning window is 2026-Q2/Q3 —
  deliberately not overlapping the regression quarter (2026-Q1) so the
  false-positive-avoidance proof is clean, not coincidental.
- Real external connectors (Gmail/Atlassian/Slack) are scoped to dedicated, isolated
  accounts only, via the new, separate Docker MCP profile `portfolio-pulse` — never touching
  the user's existing `anik` profile or the unrelated `portfolio-ops-copilot` profile found
  on this machine (belongs to a different prior project, left untouched).

## Verification status

All 9 checks from the plan run for real, on a fresh `--reset` run:
1. `pytest`: 31/31 passed. `run_tests.py`: 21/21 passed.
2. Simulation reran clean from `--reset`, identical real story every time.
3. `registry/trend-synthesizer/active.yaml` → `activated_by: pulse-auto-rollback` confirmed.
4. `investigate_incident.py` + `reproducibility_check.py` both rerun, real output, MATCH.
5. Ferrous Point: 0 systemic_flag_spike incidents ever from its own warnings (structurally
   guaranteed by the `classifying_agent` filter, not just data scheduling); Credit Committee
   clause fires exactly once, at 2026-Q3 (streak hits 2).
6. Idempotency: live double-call in the sim + 2 dedicated pytest cases, all pass.
7. Grepped for TODO/FIXME/placeholder/unrelated-project names — only legitimate hits (HTML
   `placeholder` attributes, the template substitution marker, and PROGRESS.md's own
   deliberate note about the unrelated `portfolio-ops-copilot` profile).
8. Dashboard rebuilt from this run's fresh `data_snapshot.json`; spot-checked rollback
   annotation and Ferrous Point leverage numbers match on disk; chat panel tested live in
   Chrome (real answer + real citation for 3 questions, correct "no matching record" decline
   for an off-topic question) — found and fixed a real chart-overflow CSS bug and a
   missing-charset mojibake bug during this check, before publishing.
9. Ran `--reset --live` against the still-uncredentialed profile as a deliberate proof: all
   14 notification attempts failed loudly with specific, honest per-channel reasons (missing
   config, or a real failed connection attempt to the unconfigured Gmail MCP server) — zero
   entries silently claimed `"sent"`. Repo was then reset back to a clean dry-run state for
   its committed snapshot.

Dashboard published: https://claude.ai/code/artifact/dec7fab1-0de5-45a1-a8da-a139c0e16bec
