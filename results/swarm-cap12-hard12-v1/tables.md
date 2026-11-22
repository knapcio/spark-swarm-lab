| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D roll8strategy (default, cap 8) | **81** | 0 | 15 | 61,990 | 79 min | 371 / 3062 / 3460 s | 150.1 | 1.85 | 62 | n/a |
| D12 roll12strategy (cap 12) | **85** | 0 | 11 | 76,653 | 102 min | 383 / 3939 / 4678 s | 194.0 | 2.28 | 114 | n/a |

D12 vs D paired: +6 / -2 (p = 0.289). Late rescues in D12 (answered by agents 9-12, which D never runs): 2 (2 correct). Answering slot histogram D12: {0: 19, 1: 21, 2: 23, 3: 17, 4: 1, 5: 0, 6: 2, 7: 0, 8: 1, 9: 0, 10: 1, 11: 0}.

Frozen decision rule: zero_wrong = True, late_rescues_at_least_2 = True, tokens_at_most_120pct = False, wall_at_most_125pct = False, adopt_roll12strategy = False
