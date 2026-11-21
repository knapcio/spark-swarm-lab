| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | One Inkling vs DeepSeek | Hybrid |
|---|---:|---:|---:|---:|---:|---|---|---|
| hard-v7, swarm arm B+ roll8cancel | 96 | **90** | 0 | n/a | 79 | +13 / -2 (p = 0.00739) | n/a (agent 0 often cancelled) | 92 (6 DS calls) |
| hard-v7, swarm arm B deep4cancel | 96 | **79** | 0 | n/a | 79 | +7 / -7 (p = 1) | n/a (agent 0 often cancelled) | 86 (17 DS calls) |
| hard-v7, swarm arm A deep4 | 96 | **82** | 0 | 67 | 79 | +7 / -4 (p = 0.549) | +4 / -16 (p = 0.0118) | 86 (14 DS calls) |
| Pooled v4..v7, deep4 (exploratory) | 384 | **336** | 0 | 270 | 325 | +24 / -13 (p = 0.0989) | +12 / -67 (p = 2.05e-10) | 349 (48 DS calls) |

| System on hard-v7 (96 cases, whole fleet) | Solved | Completion tokens/case | Wall | GPU energy | Wh per solved case |
|---|---:|---:|---:|---:|---:|
| Inkling swarm B+ roll8cancel | 90 | 53,641 | 71 min | 133.4 Wh | 1.48 |
| Inkling swarm B deep4cancel | 79 | 43,976 | 55 min | 103.7 Wh | 1.31 |
| Inkling swarm A deep4 | 82 | 66,592 | 90 min | 167.1 Wh | 2.04 |
| One DeepSeek (TP4, 4 nodes) | 79 | 8,146 | 65 min | 131.4 Wh | 1.66 |
