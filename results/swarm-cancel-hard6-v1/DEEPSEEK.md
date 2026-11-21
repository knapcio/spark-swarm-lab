# One DeepSeek on arithmetic-hard-v6 (deepseek-hard6-v1)

Plan [`DEEPSEEK_HARD6_PLAN.json`](../../DEEPSEEK_HARD6_PLAN.json) (f24a1f6) is a copy of the hard-v5 DeepSeek plan:
one 32K thinking call per case, same worker source, seeds 1-2, seed offset 2900, 8 concurrent requests, native DeepSeek
V4.1 TP4 over the four Sparks. It was frozen after hard-v6 existed (the corpus was generated for the swarm study) but
before any DeepSeek call on it; the corpus is pinned by sha256. Errors: []. The fleet was switched with the
reviewed procedure (`inkling/ds_switch_inkling.py`) and switched back to Inkling afterwards.

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

- **On hard-v6 the Inkling swarm (A) and One DeepSeek are level**: 86 vs 85, paired
  +3 / -2. The swarm made 0 wrong answers and abstained otherwise; of DeepSeek's
  11 misses, 5 hit the 32K budget and the rest finished within the budget without a valid plan.
- One Inkling (agent 0 of A) is clearly below One DeepSeek (73 vs 85, p = 0.0018), as on hard-v4/v5.
- Cost on the same four Sparks: the default swarm B costs about the same GPU energy per solved case as One DeepSeek
  (1.30 vs 1.29 Wh) and the same wall time for 96 cases; the old
  default A cost 1.92 Wh. DeepSeek uses ~7x fewer tokens, each far more expensive.
- Hybrid (DeepSeek only where the swarm abstains): 88/96 with 10 DeepSeek calls (A); 87/96 with 13 calls (B).
- **Exploratory pooled addendum** (the pre-registered pooled test was hard-v4 + v5 only): over v4 + v5 + v6, 288 cases,
  Inkling swarm (deep4) 254 vs One DeepSeek 246, paired +17 / -9
  (p = 0.17), 0 wrong; One Inkling 203 (p = 9e-09 below DeepSeek); hybrid 263 with
  34 DeepSeek calls. The swarm matches DeepSeek; it does not beat it significantly.

Numbers: [deepseek.json](deepseek.json); report script `inkling/report_ds_hard6.py`.
