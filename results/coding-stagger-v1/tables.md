| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy | Wh per solved | Stop median / p90 | Cases with agents 5-8 | Cancelled / never started |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E: all 8 at once (default) | **69** | 59,849 | 60 min | 114.47 Wh | 1.66 | 315 / 939 s | 72 | 491 / 0 |
| S: 4 first, 4 more after 300 s | **69** | 50,019 | 52 min | 98.18 Wh | 1.42 | 388 / 1099 s | 39 | 365 / 132 |

S vs E paired: +3 / -3 (p = 1); S/E tokens 0.836, wall 0.867, energy 0.858.

Frozen decision rule: tokens_at_most_85pct = True, solved_at_least_e_minus_2 = True, wall_at_most_110pct = True, adopt_stagger = True
