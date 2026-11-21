| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | One Inkling vs DeepSeek | Hybrid |
|---|---:|---:|---:|---:|---:|---|---|---|
| hard-v6, swarm arm A deep4 | 96 | **86** | 0 | 73 | 85 | +3 / -2 (p = 1) | +1 / -13 (p = 0.00183) | 88 (10 DS calls) |
| hard-v6, swarm arm B deep4cancel | 96 | **83** | 0 | n/a | 85 | +2 / -4 (p = 0.688) | n/a (agent 0 often cancelled) | 87 (13 DS calls) |
| hard-v6, swarm arm C waves2cancel | 96 | **81** | 0 | n/a | 85 | +3 / -7 (p = 0.344) | n/a (agent 0 often cancelled) | 88 (15 DS calls) |
| Pooled v4+v5+v6, deep4 (exploratory) | 288 | **254** | 0 | 203 | 246 | +17 / -9 (p = 0.169) | +8 / -51 (p = 9.05e-09) | 263 (34 DS calls) |

| System on hard-v6 (96 cases, whole fleet) | Solved | Completion tokens/case | Wall | GPU energy | Wh per solved case |
|---|---:|---:|---:|---:|---:|
| Inkling swarm A deep4 | 86 | 66,267 | 87 min | 165.0 Wh | 1.92 |
| Inkling swarm B deep4cancel | 83 | 44,633 | 56 min | 108.0 Wh | 1.30 |
| Inkling swarm C waves2cancel | 81 | 39,250 | 59 min | 106.8 Wh | 1.32 |
| One DeepSeek (TP4, 4 nodes) | 85 | 6,442 | 54 min | 109.98 Wh | 1.29 |
