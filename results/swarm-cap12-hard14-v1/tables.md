| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D roll8strategy (default, cap 8) | **86** | 0 | 10 | 57,012 | 73 min | 331 / 2336 / 3170 s | 141.5 | 1.65 | 61 | n/a |
| D12 roll12strategy (cap 12) | **88** | 0 | 8 | 66,975 | 91 min | 315 / 3343 / 4425 s | 172.4 | 1.96 | 98 | n/a |

D12 vs D paired: +3 / -1 (p = 0.625). Late rescues in D12 (answered by agents 9-12, which D never runs): 2 (2 correct). Answering slot histogram D12: {0: 27, 1: 19, 2: 21, 3: 16, 4: 2, 5: 0, 6: 0, 7: 1, 8: 1, 9: 0, 10: 1, 11: 0}.

Frozen decision rule: zero_wrong = True, solved_at_least_d_plus_2 = True, late_rescues_at_least_1 = True, adopt_roll12strategy = True
