| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | Case wall median / p90 | GPU Wh | Wh per solved | Agents per case | Escalated cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D roll8strategy (4 in flight, default) | **83** | 0 | 13 | 61,183 | 79 min | 327 / 2666 s | 150.3 | 1.81 | 4.72 | 20 |
| D3 roll3strategy (3 in flight) | **81** | 0 | 15 | 71,585 | 114 min | 371 / 4015 s | 206.4 | 2.55 | 4.18 | 26 |

D3 vs D paired: +2 / -4 (p = 0.688); D3/D tokens 1.17, wall 1.441, energy 1.373.

Frozen decision rule: zero_wrong = True, tokens_at_most_90pct = False, solved_at_least_d_minus_2 = True, wall_at_most_110pct = False, adopt_roll3strategy = False
