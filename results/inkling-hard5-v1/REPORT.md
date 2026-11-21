# Fresh replication on arithmetic-hard-v5 and pooled test

Plans `INKLING_HARD5_PLAN.json` and `DEEPSEEK_HARD5_PLAN.json` were frozen in 4670c56 BEFORE the corpus existed;
arithmetic-hard-v5 (generator seed 2026112101, same rules as hard-v4) was generated afterwards (13ecd62). Inkling swarm
= 4 agents with a 32K budget each plus the swarm's own thinking judge, exactly as in inkling-hard4-v1; One Inkling =
agent 0; One DeepSeek = one 32K thinking call. Errors: Inkling [], DeepSeek [].

| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | One Inkling vs DeepSeek | Hybrid |
|---|---:|---:|---:|---:|---:|---|---|---|
| hard-v4 (earlier) | 96 | **90** | 0 | 69 | 85 | +6 / -1 (p = 0.125) | +3 / -19 (p = 0.000855) | 91 (6 DS calls) |
| **hard-v5 (fresh)** | 96 | **78** | 0 | 61 | 76 | +8 / -6 (p = 0.791) | +4 / -19 (p = 0.0026) | 84 (18 DS calls) |
| **Pooled (pre-registered)** | 192 | **168** | 0 | 130 | 161 | +14 / -7 (p = 0.189) | +7 / -38 (p = 3.12e-06) | 175 (24 DS calls) |

Completion tokens per case on hard-v5: Inkling swarm 69,498, DeepSeek 10,237.
Inkling judge on hard-v5: 326 verdicts, 0 false accepts. Hybrid = swarm answer, DeepSeek only when the swarm says "no answer".
