# Generic artifact relay vs equal-budget replacement

Status: complete

| arm | status | cases | puzzles | workers | rescued | wrong | generated | prompt | prefill computed | total compute | Wh | artifact chars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| relay | complete | 29 | 6 | 116 | 5 | 0 | 3,479,160.0 | 4,950,787.0 | 931,843.0 | 4,411,003.0 | 125.9 | 1,392,000 |
| replace | complete | 29 | 6 | 116 | 2 | 0 | 3,602,442.0 | 3,566,702.0 | 51,694.0 | 3,654,136.0 | 123.5 | 0 |

total compute = generated + prefill computed (server counters; cached prompt tokens are not recomputed).

Paired (exact McNemar): relay-only rescued 4, replace-only 1, p = 0.375 over 29 cases / 6 distinct puzzles (descriptive only: the cases are not independent (several seeds of the same puzzle))

Facts: {"relay_rescued": 5, "replace_rescued": 2, "relay_wrong": 0, "replace_wrong": 0, "server_token_ratio_relay_over_replace": 0.9657782137783204, "compute_token_ratio_relay_over_replace": 1.2071261168166703, "wh_ratio_relay_over_replace": 1.0196840826245444}

Frozen rule: The hard-v18 screen replicates if RELAY rescues at least 3 more cases than REPLACE with 0 wrong in RELAY (McNemar descriptive: 6 puzzles). The in-swarm relay study proceeds only if, pooled over both screens, RELAY rescues more cases than REPLACE with 0 wrong.

Decision: evaluate the frozen rule against the facts

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.
