| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Client tokens/case | Arm wall | Case wall median / p90 | Answer time median / p90 | GPU Wh | Wh per solved | Cancelled / never started agents |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A deep4 | **86** | 0 | 10 | 66,267 | 66,267 | 87 min | 975 / 1578 s | 510 / 1505 s | 165.0 | 1.92 | 0 / 0 |
| B deep4cancel | **83** | 0 | 13 | 44,633 (-33%) | 27,736 | 56 min (-36%) | 384 / 1569 s | 384 / 1569 s | 108.0 (-34%) | 1.3 | 227 / 0 |
| C waves2cancel | **81** | 0 | 15 | 39,250 (-41%) | 33,042 | 59 min (-32%) | 474 / 2689 s | 463 / 2689 s | 106.8 (-35%) | 1.32 | 67 / 151 |

| Paired (task, seed) | Pairs | Wins | Losses | Sign test p |
|---|---:|---:|---:|---:|
| deep4cancel vs deep4 | 96 | 1 | 4 | 0.375 |
| waves2cancel vs deep4 | 96 | 2 | 7 | 0.18 |
| waves2cancel vs deep4cancel | 96 | 3 | 5 | 0.727 |

| Arm | Oracle | One Inkling (agent 0) | Judge verdicts | False accepts | False rejects | Skipped judges | Deadlines | Infra | Shim client cancels | Shim upstream errors | Segments |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A deep4 | 86 | 73 | 340 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| B deep4cancel | 83 | 32 | 131 | 0 | 0 | 0 | 0 | 0 | 227 | 0 | 1 |
| C waves2cancel | 81 | 38 | 116 | 0 | 0 | 4 | 0 | 0 | 67 | 0 | 1 |

Frozen decision rule, applied literally: non_inferior = False, tokens_at_least_15pct_lower = True, wall_not_higher = True, adopt_deep4cancel = False
