| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Loop stops (plans, accepted) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D: default (no watchdog) | **85** | 0 | 11 | 79,542 | 125 min | 227.3 | 2.67 | 0 (0, 0) |
| L: default + loop watchdog | **83** | 0 | 13 | 73,021 | 102 min | 195.7 | 2.36 | 102 (102, 0) |

L vs D paired: +1 / -3 (p = 0.625); L/D tokens 0.918, wall 0.813.

Frozen decision rule: zero_wrong = True, solved_at_least_d_minus_2 = True, tokens_at_most_95pct = True, adopt_watchdog = True

Amendment (2026-11-23, before arm L finished): arm D case eva-h247d88a63ba seed 1 lost one judge request to a transient upstream disconnect on Spark_03 (shim_upstream_errors 1, no container restart); per the frozen resume rule it was rerun with the same seeds in segment `-resume1` after arm L. This report script (frozen sha256 1812e6a68a36) was changed only to merge resume segments and to count wrong answers in superseded infra attempts against the arm; the runtime code is unchanged.
