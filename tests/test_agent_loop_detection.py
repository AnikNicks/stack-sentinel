from pulse import agent_loop_detection


def test_empty_sequence_is_zero():
    assert agent_loop_detection.max_repeat_run([]) == 0


def test_single_call_is_one():
    assert agent_loop_detection.max_repeat_run(["resolution-agent"]) == 1


def test_no_repeats_stays_one():
    assert agent_loop_detection.max_repeat_run(["a", "b", "c"]) == 1


def test_consecutive_repeats_counted():
    assert agent_loop_detection.max_repeat_run(["a", "a", "a", "a", "b"]) == 4


def test_alternating_pair_ping_pong_counted():
    seq = ["resolution-agent", "escalation-agent"] * 4  # 8 calls, pure ping-pong
    assert agent_loop_detection.max_repeat_run(seq) == 8


def test_alternating_pair_shorter_than_single_repeat_run():
    seq = ["a", "b", "a", "b"] + ["c", "c", "c", "c", "c"]
    assert agent_loop_detection.max_repeat_run(seq) == 5
