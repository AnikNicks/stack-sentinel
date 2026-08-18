# VERSIONING.md — Version Bundles, Rollback, and Two Worked Scenarios

## Version bundle format

`registry/<agent>/v1.yaml`, `v2.yaml`, `v3.yaml`, ... — each a YAML file with:

```yaml
version: v2
agent: trend-synthesizer
created: "2025-04-01"
changelog: "Compares each quarter's KPI against the trailing 3-quarter trend instead of
  only the immediately prior quarter, before calling something an inflection..."
prompt_file: .claude/agents/trend-synthesizer.md
tool_scope: [get_trend_history]
model: claude-sonnet-4-20250514
objective_statement: "Judge whether this quarter's number is a genuine inflection or
  normal noise, in the context of prior quarters."
```

`changelog` must describe the real behavioral change — not a version bump for its own sake.
Registered via `pulse.registry.register_new_version(agent, bundle)`, which **never
activates** the version it registers (`scripts/seed_registry.py` registers all of this
repo's bundles up front; nothing is active until something explicitly activates it).

## The rollback mechanism

`registry/<agent>/active.yaml` is the one-line pointer:

```yaml
agent: trend-synthesizer
active_version: v2
activated_by: pulse-auto-rollback
activated_at: "2026-08-12T23:47:50.286086+00:00"
reason: "2 of 3 companies flagged in one quarter (threshold 2) — real trouble is gradual,
  not simultaneous; this pattern is the fingerprint of an agent-version regression."
```

`pulse.registry.activate(agent, version, activated_by, reason)` is the only thing that
writes `active.yaml` — called either by a human (a deliberate upgrade) or by
`pulse.soft_fix.auto_rollback_to_last_known_good()` (the only automated caller). Every
activation also appends to `registry/<agent>/activation_log.jsonl`, which is how
`get_previous_active(agent)` finds "the version that was live immediately before this one" —
the target of a rollback.

`pulse/soft_fix.py` contains exactly one function and nothing else, by design: no LLM, no
other remediation action is ever permitted in that module. Reverting to a previously-live
version is safe unconditionally — it was already in production and known-good before the
version that replaced it — which is why `risk_scoring.py`'s systemic-flag-spike rule routes
straight here with no human gate, unlike model-boundary and policy-violation findings, which
always require a human.

## Worked scenario 1: goal drift caught and auto-rolled-back

**Actual numbers from this repo's real simulation run** (`scripts/simulate_production_run.py
--reset`, `data/scenario_facts.json`, `data/incidents/INC-0002.json`):

- `trend-synthesizer` activation history (`registry/trend-synthesizer/activation_log.jsonl`):
  `v1` (initial-deployment) → `v2` (deal-team-lead, 2025-Q2 — legitimate improvement) → `v3`
  (deal-team-lead, 2026-Q1 — the regression, innocuous-looking changelog: "Tightened
  sensitivity to short-term margin/revenue deviations to surface emerging issues earlier")
  → `v2` (**pulse-auto-rollback**, same cycle).
- 2026-Q1: Northwind's EBITDA margin dipped to 15.7% from 15.9% (a small QoQ dip against a
  clear 13.8→15.2→15.9 uptrend); Solace's same-store revenue growth dipped to 8.4% from 8.6%
  (same pattern). Both are ordinary variance, not trend breaks.
- Under `v3`, both were misclassified `off_thesis`. `risk_scoring.check_systemic_flag_spike`
  fired on `["northwind", "solace"]` (2 of 3 companies, threshold 2) → `risk_tier=critical`,
  `routing=auto_rollback`.
- Incident **`INC-0002`** created, `kind=systemic_flag_spike`, `status=auto_resolved`.
  `soft_fix.auto_rollback_to_last_known_good("trend-synthesizer", ...)` reverted to `v2`
  in the same cycle — confirmed by `registry/trend-synthesizer/active.yaml` showing
  `activated_by: pulse-auto-rollback` after the run.
- The incident's attached counterfactual (what `v2` would have said on the *identical*
  input): `{"read": "noise", ...}` → would have classified Northwind `on_thesis`. Both
  companies genuinely rebounded the very next quarter (Northwind → 16.9%, Solace → 8.6%)
  under the restored `v2`, corroborating the rollback was correct.
- `scripts/investigate_incident.py` and `scripts/reproducibility_check.py` both run against
  `INC-0002` directly from disk — see their real output in
  `PRODUCTION_READINESS_REPORT.md`.

## Worked scenario 2: a genuine model boundary, routed to a human

**Actual numbers from the same run** (`data/incidents/INC-0003.json`):

- Solace's `trend-synthesizer` classifying entries for 2026-Q2 and 2026-Q3 both carry
  `agent_version: v2` (unchanged) — but the `model` field differs:
  `claude-sonnet-4-20250514` (Q2) → `claude-sonnet-4-5-20250929` (Q3). This is the realistic
  case the policy corpus's model-boundary clause exists for: a pinned *version* looking
  unchanged doesn't guarantee the pinned *model* actually resolved to the same snapshot for
  every call.
- `pulse.model_boundary.detect_boundary` on these two entries: version unchanged, model
  changed → `"model_boundary"`. Solace's classification flipped `on_thesis` (Q2) →
  `off_thesis` (Q3) even though same-store revenue growth (8.6% → 8.3%) stayed well within
  its normal trailing range (8.0%–8.7%).
- `risk_scoring.check_model_boundary_ambiguity("model_boundary")` →
  `risk_tier=high, routing=human_review` — **unconditional**, regardless of confidence.
  Incident **`INC-0003`** created, `status=pending_review`.
- This is the direct application of the policy clause quoted in
  `policy/monitoring_escalation_policy.md`: *"Any classification change attributable to a
  change in the underlying model or agent version, rather than a change in the company's
  actual financial position, must not be used as the sole basis for an escalation decision
  without human confirmation."* That clause is the policy-level justification for why
  model-boundary events are unconditionally human-gated in `risk_scoring.py` — there is no
  code path that lets a model-boundary finding auto-resolve, by design.
- `pulse.incidents.record_human_review(...)` was called with `resolved_by:
  "jordan.lee@dealteam.example.com"`, confirming: *"Confirmed model-interpretation noise...
  No escalation taken on this classification alone."* Final status: `reviewed`. Solace's
  subsequent quarter (2026-Q4, growth back to 8.6%) confirmed there was no real business
  change to react to.

## Why `compound_boundary` should never happen in a real deployment

If `agent_version` and `model` both change in the same release, a broken trend afterward is
unrootcauseable — you cannot tell whether the version change, the model change, or their
interaction is responsible (`pulse/model_boundary.py`'s docstring makes this explicit).
`risk_scoring.py` treats `compound_boundary` as `risk_tier=critical` (one tier above a plain
`model_boundary`) specifically to reflect that it's a worse, harder-to-diagnose case — but the
real fix is operational discipline: change one axis at a time, always.
