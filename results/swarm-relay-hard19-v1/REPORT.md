# swarm-relay-hard19-v1

| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated/case | prompt/case | prefill computed/case | total compute/case | wall s | Wh | Wh/solved |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G | roll12cancel | complete | 96 | 84 | 0 | 12 | 83,717.6 | 63,476.7 | 1,674.1 | 85,391.6 | 6,589.8 | 208.1 | 2.477 |
| RL | roll12relay | complete | 96 | 83 | 0 | 13 | 83,455.3 | 79,549.8 | 11,976.5 | 95,431.8 | 6,696.7 | 214.4 | 2.584 |

Paired: RL-only solved 0, G-only 1, exact sign test p = 1.

## Escalation and relay

| arm | answered by escalation (slot >= 4) | solved | answered by relayed agents | solved | relayed agents started |
|---|---|---|---|---|---|
| G | 6 | 6 | 0 | 0 | 0 |
| RL | 6 | 6 | 6 | 6 | 138 |

Total compute = generated + computed prefill (server counters, all segments).

## Decision (complete inputs, unrounded values)

Rule: RL (roll12relay) replaces G (roll12cancel) as the arithmetic default if RL has 0 wrong, RL solved >= G solved, and RL answers at least as many cases through escalation agents as G. Cost and wall are reported, not gated (owner priority: quality).

Evaluation: {"zero_wrong": true, "solved_at_least_G": false, "escalation_answers_at_least_G": true, "RL_replaces_G": false}

## Wrong answers over all attempts and wasted work

- G: 0 wrong attempt(s)
- RL: 0 wrong attempt(s)

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.

Design notes: (1) G and RL share slots 0-3 exactly (seeds, nodes, prompts); escalation agents run on the node of the agent whose end freed their slot, so their nodes can differ between arms; (2) each request's sampling seed hashes the prompt, so RL's escalation agents (prompt + relayed work) sample differently from G's even with equal agent seeds; (3) the relayed work is chosen by seeded uniform sampling among the case's already failed agents, never by content; (4) the plan's code_sha256 pins are records checked by review, not enforced by the runner.
