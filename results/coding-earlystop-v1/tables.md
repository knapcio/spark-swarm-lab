| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy | Wh per solved | Cancelled / never started agents |
|---|---:|---:|---:|---:|---:|---:|
| F: 8 agents to the end (slot-order first passing) | **66** | 99,752 | 96 min | 180.69 Wh | 2.74 | 0 / 0 |
| E: stop at first passing in time | **69** | 62,790 (-37 %) | 61 min (-36 %) | 116.57 Wh | 1.69 | 495 / 0 |

E vs F paired: +5 / -2 (p = 0.45). Inside F (same proposals, no generation noise): time-order pick 71 vs slot-order pick 66 (selection effect +5). F oracle 72, One Inkling (agent 0) 62.

Frozen decision rule: selection_effect_at_least_minus_1 = True, tokens_at_most_80pct = True, wall_lower = True, adopt_early_stop = True
