# swarm-aot-hard21-v1: Atom of Thoughts in the swarm

| arm | status | cases | solved | wrong (all attempts) | abstain | generated | total compute | wall s | Wh | Wh/solved |
|---|---|---|---|---|---|---|---|---|---|---|
| P | complete | 96 | 89 | 0 | 7 | 6,654,006.0 | 6,828,656.0 | 3,887.7 | 133.1 | 1.496 |
| A | complete | 96 | 82 | 0 | 14 | 14,054,410.0 | 19,825,859.0 | 8,366.2 | 283.3 | 3.455 |

Transport retries per arm (A: charged to the agent budget; P: accounting only): P {"retries": 0, "lost_completion_tokens": 0, "retries_not_sent": 0}, A {"retries": 0, "lost_completion_tokens": 0, "retries_not_sent": 0}

Paired: AoT-only solved 0, plain-only 7, exact sign test p = 0.01562.

AoT agents: {"agents": 333, "round1_unparsed": 7, "contracted": 326, "with_facts": 326, "facts": 653, "accepted_with_facts": 88, "round1_decomposed": 326}

## Decision (complete inputs, unrounded values)

Rules: {"P": "AoT is adopted if A has 0 wrong over all attempts, A solved >= P solved + 3, and A server generation tokens <= 1.10 x P (exact, complete pairing).", "A": "AoT is adopted if A has 0 wrong over all attempts, A solved >= P solved + 3, and A server generation tokens <= 1.10 x P (exact, complete pairing)."}

Evaluation: {"zero_wrong": true, "solved_at_least_plain_plus_3": false, "tokens_at_most_110pct": false, "AoT_adopted": false}

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.

Atom of Thoughts: Teng et al. 2025 (arXiv 2502.12018, github.com/qixucen/atom); the task-graph framing follows alkimiadev's taskgraph idea. Both arms run the same worker source revision; the AoT agent uses the plain agent's per-agent completion-token budget (32,768) and the same agent count, so the compute cap is equal. Asymmetry: an AoT agent's transport retry is charged to its own budget and counts toward its call cap; a plain agent's (rare) retry is not charged to its budget (reviewed behaviour kept), only to the accounting. A lost attempt's streamed-token count is a lower bound of the server's work on it, so an AoT agent can exceed 32,768 server-counted tokens by the unstreamed part of a lost attempt; the server counters used by the decision include it.
