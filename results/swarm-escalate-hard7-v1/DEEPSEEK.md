# One DeepSeek on arithmetic-hard-v7 (deepseek-hard7-v1)

Plan [`DEEPSEEK_HARD7_PLAN.json`](../../DEEPSEEK_HARD7_PLAN.json) is a copy of the hard-v5/v6 DeepSeek plan: one 32K thinking
call per case, same worker source, seeds 1-2, seed offset 2900, 8 concurrent requests, native DeepSeek V4.1 TP4 over the
four Sparks. Frozen after hard-v7 existed but before any DeepSeek call on it; the corpus is pinned by sha256. Errors:
[]. The fleet was switched with the reviewed procedure and switched back to Inkling afterwards.

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

- **New default swarm B+ vs One DeepSeek: 90 vs 79, paired +13 / -2
  (p = 0.0074)**, 0 wrong answers for the swarm. Old default A: 82 (+7 / -4).
- Hybrid (DeepSeek only where the swarm abstains): B+ 92/96 with 6 DeepSeek calls; A 86 with 14.
- Cost on the same four Sparks: B+ 1.48 Wh per solved case, One DeepSeek
  1.66, A 2.04; wall 71 vs 65 vs 90 min for 96 cases.
  Inkling ran at --mem-fraction-static 0.62 during hard-v7 (the KV raise came afterwards).
- One Inkling (agent 0 of A) vs One DeepSeek: 67 vs 79 (p = 0.012).
- Exploratory pooled addendum, deep4 only, hard-v4..v7 (384 cases): swarm 336 vs DeepSeek 325,
  +24 / -13 (p = 0.099).

Numbers: [deepseek.json](deepseek.json); report script `inkling/report_ds_hard7.py`.
