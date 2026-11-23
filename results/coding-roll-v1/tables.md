| Arm | Solved /72 | Wrong | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Stop median / p90 | Agents started per case |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S: early stop + stagger 4+4 at 300 s (default) | **65** | 5 | 50,750 | 53 min | 99.03 | 1.52 | 340 / 1056 s | 6.11 |
| R4: replace failures, 4 in flight | **69** | 2 | 38,206 (-25 %) | 47 min | 83.79 | 1.21 | 362 / 848 s | 4.18 |
| R2: replace failures, 2 in flight | **71** | 1 | 24,275 (-52 %) | 49 min | 71.83 | 1.01 | 405 / 1089 s | 2.15 |

R4 vs S paired: +7 / -3 (p = 0.34). R2 vs S paired: +6 / -0 (p = 0.031). 

Frozen decision rule (R2 if solved >= S - 2 and tokens <= 0.70 x S; else R4 if solved >= S - 2 and tokens <= 0.85 x S; else S): adopt **R2**.
