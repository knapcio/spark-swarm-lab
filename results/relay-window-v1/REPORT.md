# Artifact relay: tail window vs dense window

Status: complete

| arm | status | cases | puzzles | workers | rescued | wrong | generated | prompt | prefill computed | total compute | Wh | artifact chars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tail | complete | 38 | 13 | 81 | 1 | 0 | 2,514,457.0 | 3,925,386.0 | 755,466.0 | 3,269,923.0 | 93.0 | 972,000 |
| dense | complete | 38 | 13 | 81 | 1 | 0 | 2,490,727.0 | 3,613,383.0 | 638,535.0 | 3,129,262.0 | 80.9 | 972,000 |

total compute = generated + prefill computed (server counters; cached prompt tokens are not recomputed).

Paired (exact McNemar): tail-only rescued 1, dense-only 1, p = 1 over 38 cases / 13 distinct puzzles (descriptive only: the cases are not independent (several seeds of the same puzzle))

Facts: {"tail_rescued": 1, "dense_rescued": 1, "tail_wrong": 0, "dense_wrong": 0, "server_token_ratio_tail_over_dense": 1.0095273388050958, "compute_token_ratio_tail_over_dense": 1.0449502150986398, "wh_ratio_tail_over_dense": 1.1493883603113801, "rescues_per_window": {"tail": 1, "dense": 1}, "changed_workers": 81, "changed_workers_started_in_both": 81, "accepted_workers": {"tail": 1, "dense": 1}, "accepted_workers_started_in_both": {"tail": 1, "dense": 1}}

Frozen rule: roll12relay switches to the dense window (after the in-swarm study adopts relay) if dense rescues more cases than tail with 0 wrong; otherwise the tail stays. McNemar reported, descriptive (12 puzzles).

Decision: evaluate the frozen rule against the facts

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.
