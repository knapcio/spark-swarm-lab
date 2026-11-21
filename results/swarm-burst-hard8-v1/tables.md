| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts (false) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B+ roll8cancel (default) | **91** | 0 | 5 | 47,278 | 66 min | 325 / 1563 / 2903 s | 123.7 | 1.36 | 44 | 0 (0) |
| B++ roll12burst (cap 12, burst at 900 s) | **90** | 0 | 6 | 70,657 | 91 min | 458 / 2280 / 3663 s | 174.7 | 1.94 | 125 | 21 (9) |

B++ vs B+ paired: +2 / -3 (p = 1). Late rescues in B++ (answered by agents 9-12, which B+ never runs): 4 (4 correct). Answering slot histogram B++: {0: 19, 1: 21, 2: 23, 3: 21, 4: 0, 5: 1, 6: 0, 7: 1, 8: 0, 9: 2, 10: 0, 11: 2}.

Frozen decision rule: zero_wrong = True, tokens_at_most_115pct = False, late_rescues_at_least_2 = True, wall_at_most_90pct = False, adopt_roll12burst = False
