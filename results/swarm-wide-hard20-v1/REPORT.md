# swarm-wide-hard20-v1

| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated | total compute | wall s | Wh | Wh/solved | judge latency p90 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| G | roll12cancel | complete | 96 | 87 | 0 | 9 | 7,168,772.0 | 7,318,269.0 | 6,085.6 | 193.3 | 2.221 | 53.0 |
| W | roll12wide | complete | 96 | 87 | 0 | 9 | 7,248,453.0 | 7,385,724.0 | 5,476.1 | 175.8 | 2.02 | 54.7 |

Paired: W-only solved 3, G-only 3, exact sign test p = 1.

## Widening (W)

- cases that widened: 14; widened agents: 58; median time to the first widened start: 2,424.8 s
- max agents in flight per case (histogram): {'4': 82, '6': 1, '7': 1, '8': 12}

Facts (W / G): {"wall_ratio_w_over_g": 0.8998526784849596, "generated_tokens_ratio": 1.0111150138405853, "total_compute_ratio": 1.009217343609534, "wh_ratio": 0.9095048377916903}

## Decision (complete inputs, unrounded values)

Rule: W (roll12wide) replaces G (roll12cancel) as the arithmetic default if W has 0 wrong, W solved >= G solved - 2 (noise band), and W arm wall <= 0.95 x G arm wall (exact, from UTC timestamps).

Evaluation: {"zero_wrong": true, "solved_within_noise": true, "wall_at_most_95pct_of_G": true, "W_replaces_G": true}

## Wrong answers over all attempts and wasted work

- G: 0 wrong attempt(s)
- W: 0 wrong attempt(s)

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.

Design notes: (1) G and W run the same agents with the same prompts and seeds (slots pair exactly); W only moves start times: once no case waits for admission, a case with at least one failed agent may start its next slots up to 8 in flight, oldest case first, least-loaded node first, keeping 2 permits per node free for judges; widened slots may run on another node than in G; (2) the trigger is slot occupancy and failure counts, never elapsed time and never task content; (3) the plan's code_sha256 pins are records checked by review, not enforced by the runner.
