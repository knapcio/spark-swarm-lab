# swarm-generic-hard18-v1

| arm | policy | status | cases | solved | wrong (all attempts) | abstain | server tokens/case | wall s | Wh | Wh/solved |
|---|---|---|---|---|---|---|---|---|---|---|
| S | roll12strategy | complete | 96 | 83 | 0 | 13 | 83,528.7 | 6,559.9 | 207.0 | 2.494 |
| G | roll12cancel | complete | 96 | 85 | 0 | 11 | 81,582.4 | 6,361.7 | 202.0 | 2.376 |
| GI | roll12idle | complete | 96 | 86 | 0 | 10 | 101,777.8 | 7,898.7 | 253.9 | 2.952 |

## Paired exact sign tests

- G vs S: G-only solved 4, S-only 2, p = 0.6875
- GI vs G: GI-only solved 4, G-only 3, p = 1

## GI idle-capacity escalation (slots 12-19)

- cases reaching the idle phase: 11; extra agents started: 88 (per idle case: [8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8])
- cases answered by a slot >= 12: 1 (solved 1, wrong 0)
- node occupancy when an extra agent started (started agents only): n 88, median 11.0, max 11, histogram {'9': 2, '10': 7, '11': 79}
- node occupancy when an extra agent's judge was admitted: n 45, max 11, cancelled while waiting 1, histogram {'0': 2, '1': 2, '2': 1, '3': 3, '4': 3, '5': 1, '6': 4, '7': 3, '8': 1, '9': 1, '10': 2, '11': 22}

## Decisions (complete inputs, unrounded values)

- G: {"zero_wrong": true, "solved_within_noise": true, "G_replaces_S": true}
- GI: {"zero_wrong": true, "solved_at_least_G": true, "answered_by_extra_slot": true, "wall_at_most_110pct_of_G": false, "GI_replaces_G": false}

Frozen rules: G (roll12cancel) replaces S as the arithmetic default if G has 0 wrong and G solved >= S solved - 2 (noise band; the owner rule prefers the generic policy). GI (roll12idle) then replaces G if GI has 0 wrong, GI solved >= G solved, at least 1 case is answered by a slot >= 12, and GI arm wall <= 1.10 x G arm wall.

## Wrong answers over all attempts and wasted work

- S: 0 wrong attempt(s)
- G: 0 wrong attempt(s)
- GI: 0 wrong attempt(s)

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.

Design notes: (1) escalation agents run on the node of the agent whose end freed their slot, so the same slot can run on different nodes in different arms; (2) each request's sampling seed hashes the agent seed, stage and prompt token ids, so S (hinted prompts) and G/GI (no hints) sample differently for escalation agents even with equal agent seeds, while G and GI share slots 0-11 exactly in seeds and prompts; (3) GI's extra agents depend on node occupancy in the shared slots (agents + judges of all cases of the arm), i.e. on the arm's own load, never on elapsed time; (4) the plan's code_sha256 pins are records checked by review, not enforced by the runner; arms.py must be given --source for the worker revision.
