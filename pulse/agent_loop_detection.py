"""Real longest-repeated-run count over a literal call sequence — the deterministic detector
behind pulse/risk_scoring.check_agent_loop. A "loop" here means the same agent (or the same
back-and-forth pair) appearing consecutively far more than a single real hand-off would ever
require — a literal, countable fact about a provided sequence, not a judgment call.
"""

from __future__ import annotations


def max_repeat_run(call_sequence: list[str]) -> int:
    """Longest run of immediately-consecutive identical entries in call_sequence. A sequence
    that alternates between two agents every single call (A, B, A, B, ...) is exactly the
    ping-pong pattern a real hand-off loop produces just as much as one agent repeating itself
    (A, A, A, ...) — so this counts the longer of: the longest single-value run, and the
    longest strictly-alternating-pair run."""
    if not call_sequence:
        return 0

    longest_single = 1
    current = 1
    for prev, curr in zip(call_sequence, call_sequence[1:]):
        if curr == prev:
            current += 1
            longest_single = max(longest_single, current)
        else:
            current = 1

    longest_pair_cycle = 1
    if len(call_sequence) >= 3:
        current_pair = 2
        for i in range(2, len(call_sequence)):
            if call_sequence[i] == call_sequence[i - 2] and call_sequence[i] != call_sequence[i - 1]:
                current_pair += 1
                longest_pair_cycle = max(longest_pair_cycle, current_pair)
            else:
                current_pair = 2

    return max(longest_single, longest_pair_cycle if len(call_sequence) >= 3 else 1)
