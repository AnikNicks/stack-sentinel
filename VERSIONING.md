# VERSIONING.md — Version Bundles, Rollback, and Three Worked Scenarios

## Version bundle format

`registry/<agent>/v1.yaml`, `v2.yaml`, `v3.yaml`, ... — each a YAML file with:

```yaml
version: v2
agent: change-impact-synthesizer
created: "2025-02-03"
changelog: "Requires the change_event to plausibly explain the specific finding (not just
  co-occur in the same cycle) before calling it attributable..."
prompt_file: .claude/agents/change-impact-synthesizer.md
tool_scope: [get_trend_history]
model: claude-sonnet-4-20250514
objective_statement: "Judge whether this cycle's finding is attributable to a real
  layer-change event or is noise, in the context of prior cycles."
```

`changelog` must describe the real behavioral change — not a version bump for its own sake.
Registered via `pulse.registry.register_new_version(agent, bundle)`, which **never
activates** the version it registers. `scripts/seed_registry.py` registers all of this repo's
bundles up front, then runs each one through `pulse.benchmarks.run_benchmark_suite` — a
second, earlier safety gate a human reviews before ever calling `activate()`. Nothing is
active until something explicitly activates it.

## The rollback mechanism

`registry/<agent>/active.yaml` is the one-line pointer:

```yaml
agent: change-impact-synthesizer
active_version: v2
activated_by: pulse-auto-rollback
activated_at: "2026-08-18T07:36:29.625179+00:00"
reason: "2 of 3 companies flagged in one cycle (threshold 2) — real trouble is gradual,
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
straight here with no human gate, unlike model-boundary, policy-violation, and
destructive-layer-change findings, which always require a human. Destructive changes go
further than "require a human" — `pulse/human_approval.py` guarantees no automated path
exists at all, not even a gated one; `soft_fix.py` is the *only* place this codebase performs
an automated remediation, and it only ever does one specific, safe thing.

## Worked scenario 1: goal drift caught and auto-rolled-back

**Actual numbers from this repo's real simulation run** (`scripts/simulate_production_run.py
--reset`, `data/scenario_facts.json`, `data/incidents/INC-0002.json`):

- `change-impact-synthesizer` activation history
  (`registry/change-impact-synthesizer/activation_log.jsonl`): `v1` (initial-deployment) →
  `v2` (engineering-lead, 2025-S02 — legitimate improvement, requires the change_event to
  plausibly explain the specific finding) → `v3` (engineering-lead, 2025-S06 — the
  regression, innocuous-looking changelog: "Tightened sensitivity to short-term deviations to
  surface emerging issues earlier") → `v2` (**pulse-auto-rollback**, same cycle).
- 2025-S06: compliance monitoring flagged, for both Meridian and Wayfinder, an audit-log
  ordering discrepancy (a refund/booking completion timestamp preceding its
  approval/confirmation timestamp by ~1-2 seconds) — on its face a real boundary hit, but in
  fact a benign timestamp-write-order artifact of that cycle's own routine layer change (a
  prompt-template config update for Meridian, a provider-side MCP integration bump for
  Wayfinder), confirmed by each system's own session logs.
- `goal-drift-tracker` raw-classified both `drifted` — a defensible raw read given the
  ordering discrepancy alone. Under `v3`, `change-impact-synthesizer` read both as
  `attributable` (wrongly treating "a change_event co-occurred" as sufficient grounds to keep
  the raw flag, without checking whether that change_event could plausibly explain *this*
  specific finding). `risk_scoring.check_systemic_flag_spike` fired on
  `["meridian", "wayfinder"]` (2 of 3 companies, threshold 2) → `risk_tier=critical`,
  `routing=auto_rollback`.
- Incident **`INC-0002`** created, `kind=systemic_flag_spike`, `status=auto_resolved`.
  `soft_fix.auto_rollback_to_last_known_good("change-impact-synthesizer", ...)` reverted to
  `v2` in the same cycle — confirmed by `registry/change-impact-synthesizer/active.yaml`
  showing `activated_by: pulse-auto-rollback` after the run.
- The incident's attached counterfactual (what `v2` would have said on the *identical*
  input): `{"read": "noise", ...}` for both companies → would have classified both
  `on_charter`. Both companies stayed clean the very next cycle (S07 onward) under the
  restored `v2`, corroborating the rollback was correct.
- `scripts/investigate_incident.py` and `scripts/reproducibility_check.py` both run against
  `INC-0002` directly from disk — see their real output in
  `PRODUCTION_READINESS_REPORT.md`.

## Worked scenario 2: a genuine model boundary, routed to a human

**Actual numbers from the same run** (`data/incidents/INC-0004.json`):

- Wayfinder's `change-impact-synthesizer` classifying entries for 2025-S08 and 2025-S09 both
  carry `agent_version: v2` (unchanged, already rolled back from the S06 incident) — but the
  `model` field differs: `claude-sonnet-4-20250514` (S08) →
  `claude-sonnet-4-5-20250929` (S09). This is the realistic case the policy corpus's
  model-boundary clause exists for: a pinned *version* looking unchanged doesn't guarantee
  the pinned *model* actually resolved to the same snapshot for every call.
- `pulse.model_boundary.detect_boundary` on these two entries: version unchanged, model
  changed → `"model_boundary"`. Wayfinder's classification flipped `on_charter` (S08, zero
  behavior_incidents) → `drifted` (S09) after the same benign audit-log ordering artifact
  from S06 recurred, this time following a routine MCP tool version bump (v4 → v4.1) —
  and this cycle's model read it as `attributable` where the S06-era model, under the
  restored v2 prompt, would not have.
- `risk_scoring.check_model_boundary_ambiguity("model_boundary")` →
  `risk_tier=high, routing=human_review` — **unconditional**, regardless of confidence.
  Incident **`INC-0004`** created, `status=pending_review`.
- This is the direct application of the policy clause quoted in
  `policy/monitoring_escalation_policy.md`: *"Any classification change attributable to a
  change in the underlying model or agent version, rather than a change in the monitored
  system's actual behavior, must not be used as the sole basis for an escalation decision
  without human confirmation."* That clause is the policy-level justification for why
  model-boundary events are unconditionally human-gated in `risk_scoring.py` — there is no
  code path that lets a model-boundary finding auto-resolve, by design.
- `pulse.incidents.record_human_review(...)` was called with `resolved_by:
  "priya.nair@platform-reliability.example.com"`, confirming: *"...confirmed as
  model-interpretation noise, not a real boundary violation. No escalation taken on this
  classification alone."* Final status: `reviewed`.

## Worked scenario 3: a destructive layer change, never auto-executed

**Actual numbers from the same run** (`data/incidents/INC-0003.json`):

- 2025-S08: Cascade's `database` layer proposed a schema migration —
  `DROP TABLE raw_events_archive (4.2M rows)` — flagged `reversible: false` in its
  change_event, ahead of a cold-storage cutover.
- `pulse.layer_versioning.detect_layer_change("database", prev_layers, curr_layers)`
  classified this `destructive_change_candidate` — purely from the literal `reversible` flag,
  no judgment call, no agent involved.
- `risk_scoring.check_destructive_layer_change(...)` fired unconditionally →
  `risk_tier=critical`, `routing=pending_human_approval`. Incident **`INC-0003`** created,
  `status=pending_human_approval`.
- `pulse.human_approval.gate_destructive_action(...)` was called and returned
  `{"action_taken": False, "status": "pending_human_approval", ...}` — the migration was
  **not executed**. No code path in this repository could have executed it at this point;
  the module has exactly one function and it never returns `action_taken: True`.
- Only afterward, as a separate and explicit step, was
  `pulse.incidents.record_approval_decision("INC-0003", "approved", ...)` called, with
  `resolved_by: "morgan.reyes@data-governance.example.com"` and the note *"Confirmed
  pre-approved by data governance; cold-storage migration of raw_events_archive verified
  complete before the drop."* Final status: `approved`. Recording that decision performs no
  action itself — actually applying the migration is a deliberate step outside this system's
  own authority, exactly as `policy/monitoring_escalation_policy.md`'s "Destructive and
  irreversible layer changes" clause requires.

## Why `compound_boundary` should never happen in a real deployment

If `agent_version` and `model` both change in the same release, a broken trend afterward is
unrootcauseable — you cannot tell whether the version change, the model change, or their
interaction is responsible (`pulse/model_boundary.py`'s docstring makes this explicit).
`risk_scoring.py` treats `compound_boundary` as `risk_tier=critical` (one tier above a plain
`model_boundary`) specifically to reflect that it's a worse, harder-to-diagnose case — but the
real fix is operational discipline: change one axis at a time, always.
