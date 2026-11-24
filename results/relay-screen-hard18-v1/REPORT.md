# Generic artifact relay vs equal-budget replacement

Status: complete

| arm | status | cases | puzzles | workers | rescued | wrong | generated | prompt | prefill computed | total compute | Wh | artifact chars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| relay | complete | 14 | 7 | 56 | 4 | 0 | 1,623,907.0 | 2,245,092.0 | 466,660.0 | 2,090,567.0 | 59.5 | 672,000 |
| replace | complete | 14 | 7 | 56 | 0 | 0 | 1,759,034.0 | 1,755,574.0 | 33,718.0 | 1,792,752.0 | 61.2 | 0 |

total compute = generated + prefill computed (server counters; cached prompt tokens are not recomputed).

Paired (exact McNemar): relay-only rescued 4, replace-only 0, p = 0.125 over 14 cases / 7 distinct puzzles (descriptive only: the cases are not independent (several seeds of the same puzzle))

Facts: {"relay_rescued": 4, "replace_rescued": 0, "relay_wrong": 0, "replace_wrong": 0, "server_token_ratio_relay_over_replace": 0.9231811323715176, "compute_token_ratio_relay_over_replace": 1.1661216944675001, "wh_ratio_relay_over_replace": 0.9710926016658501}

Frozen rule: Go to a frozen fresh-corpus study of relay inside the default swarm only if RELAY rescues at least 3 more cases than REPLACE with 0 wrong in RELAY (exact McNemar reported). Otherwise artifact relay is not pursued (rejection to astra review).

Decision: evaluate the frozen rule against the facts

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.
