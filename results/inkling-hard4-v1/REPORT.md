# Inkling-2-Mini Swarm v2 on arithmetic-hard-v4 (96 cases)

Plan `INKLING_HARD4_PLAN.json` (frozen in 76c9e42 before any Inkling call on these tasks). Same 48 tasks x seeds 1-2,
harness source d94c893, deep4 policy (4 agents, 32K budget each, budget forcing), arbiter-free selection by the
swarm's own thinking judge, exact verifier only for scoring. Only the served model changes: Inkling-2-Mini
(SGLang DSpark recipe, `inkling/TUNING.md`) instead of Nemotron 3.5 Lightning. Nemotron and DeepSeek rows are the
existing runs on the same cases. Errors: []; infra 0, deadlines 0.
Wall time 172 min on four Sparks (shared with the coding run).

| 96 cases (48 tasks x 2 seeds) | Solved | Wrong answers | No answer | Any of 4 agents right | Completion tokens / case |
|---|---:|---:|---:|---:|---:|
| **Inkling Swarm (4 x 32K + own judge)** | **90** | 0 | 6 | 90 | 61,642 |
| One Inkling (agent 0) | 69 | | | | |
| Nemotron Swarm v2 (same setup) | 82 | 0 | 14 | 82 | 92,820 |
| One Nemotron (agent 0) | 54 | | | | |
| One DeepSeek V4.1 (32K) | 85 | | | | 6,486 |
| Hybrid: Inkling Swarm, DeepSeek only on "no answer" | 91 | | | | 6 DeepSeek calls |

Paired over 96 cases (two-sided exact sign test on discordant cases):
- Inkling Swarm vs One DeepSeek: +6 / -1, p = 0.125
- Inkling Swarm vs Nemotron Swarm v2: +9 / -1, p = 0.0215
- One Inkling vs One DeepSeek: +3 / -19, p = 0.000855

Per seed, Inkling Swarm: seed 1 44/48, seed 2 46/48.
Inkling judge: 330 verdicts, 0 false accepts, 2 false rejects (exact verifier as reference).
