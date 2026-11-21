# Inkling-2-Mini coding swarm on coding-hard-v1 (72 cases)

Plan `INKLING_CODING_PLAN.json` (frozen in 76c9e42; amendment 1 = per-request wall limit 1800 -> 14400 s, source c2eb89e,
unfinished and faulted agents rerun in v1b). 24 evaluation tasks x 3 seeds, 8 independent code_xl agents (32K budget),
selection = first agent in fixed order whose code passes the public feedback cases; solved = that code passes the hidden
holdout cases. Nemotron rows: the same setup (coding-hard-xl-v1/v1b/ext). DeepSeek: one 32K call per case.
All 576 Inkling agents present: True; faulted records dropped and rerun: 6.

| 72 cases | k=1 | k=2 | k=3 | k=4 | k=5 | k=6 | k=7 | k=8 | Any of 8 right | Wrong answers (k=8) | Tokens / case (8 agents) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Inkling** | 62 | 66 | 67 | 68 | 68 | 68 | 68 | 69 | 71 | 2 | 101,889 |
| Nemotron | 37 | 44 | 49 | 51 | 52 | 53 | 55 | 56 | 64 | 10 | 175,955 |
| One DeepSeek V4.1 | 61 | | | | | | | | | | 12,229 |

- Inkling 8-agent swarm vs One DeepSeek: +10 / -2, p = 0.0386
- Inkling 8 vs Nemotron 8: +15 / -2, p = 0.00235
- One Inkling vs One DeepSeek: +8 / -6, p = 0.791
- Hybrid (DeepSeek only where no Inkling agent passed feedback): 69/72 with 1 DeepSeek calls.
