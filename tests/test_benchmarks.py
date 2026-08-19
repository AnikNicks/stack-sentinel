from pulse import benchmarks


def test_registered_suites_exist_for_classifying_agents():
    for agent in ("goal-drift-tracker", "slo-risk-tracker", "change-impact-synthesizer",
                  "model-boundary-interpreter", "policy-compliance-checker", "groundedness-checker"):
        assert benchmarks.BENCHMARK_SUITES.get(agent), f"no benchmark cases registered for {agent}"


def test_run_benchmark_suite_all_pass_when_classify_fn_is_correct():
    def correct_classify(input_context):
        # Mirrors the real goal-drift-tracker rubric closely enough to pass both cases.
        if input_context["behavior_incidents"]:
            return {"raw_classification": "drifted", "rationale": "boundary violated"}
        return {"raw_classification": "on_charter", "rationale": "no incidents"}

    result = benchmarks.run_benchmark_suite("goal-drift-tracker", "v1", correct_classify)
    assert result.all_passed
    assert result.failures == []
    assert result.total == len(benchmarks.BENCHMARK_SUITES["goal-drift-tracker"])


def test_run_benchmark_suite_reports_failures_without_raising():
    def always_on_charter(input_context):
        return {"raw_classification": "on_charter", "rationale": "always fine"}

    result = benchmarks.run_benchmark_suite("goal-drift-tracker", "v3", always_on_charter)
    assert not result.all_passed
    assert result.passed < result.total
    assert any(f["case"] == "clear_boundary_violation_flags_drifted" for f in result.failures)


def test_unregistered_agent_returns_empty_result():
    result = benchmarks.run_benchmark_suite("not-a-real-agent", "v1", lambda ctx: {})
    assert result.total == 0
    assert result.all_passed
