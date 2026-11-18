# Fresh confirmation: 32K Nemotron swarm vs DeepSeek on arithmetic-hard-v4

Plans frozen before the corpus existed: `CONFIRM_XL_HARD4_PLAN.json` (Nemotron deep4, 4 deep agents with 32K budget, arbiter-free judge selection, 128K serving clones; amendment: v1 aborted after 5 cases because I overloaded the servers, v2 = full rerun) and `DEEPSEEK_HARD4_PLAN.json` (DeepSeek V4.1, one 32K call per task, frozen right after generation, run after the Nemotron run finished). arithmetic-hard-v4 = 48 fresh evaluation tasks (generator seed 2026111703), seed 1. Errors: Nemotron [], DeepSeek [].

| System (48 fresh hard tasks) | Solved | Wrong answers | No answer | Completion tokens / task |
|---|---:|---:|---:|---:|
| **Nemotron deep4 32K (swarm, own judge)** | **41** | 0 | 7 | 95,234 |
| DeepSeek 32K, 1 call | 42 | | | 6,138 |
| Nemotron single agent 32K (agent 0) | 30 | | | |
| Hybrid: swarm, DeepSeek only on "no answer" | 44 | | | 7 DeepSeek calls |

Paired swarm vs DeepSeek: +2 / -3 (both failed: 4). Oracle any-of-4: 41/48.

Reading: on fresh tasks, frozen in advance, the arbiter-free Nemotron swarm with a 32K thinking budget is level with DeepSeek (41 vs 42 of 48) and never answered wrongly. This confirms the hard-v3 finding (38 vs 39). The hybrid (Nemotron first, DeepSeek only when the swarm says "no answer") reaches 44/48 with 7 DeepSeek calls instead of 48.


## Seed-2 replication (added 2026-11-18 ~06:00)

Plans `CONFIRM_XL_HARD4_SEED2_PLAN.json` and `DEEPSEEK_HARD4_SEED2_PLAN.json`, frozen before any seed-2 call; same 48 tasks, new seeds for both systems; errors [] in both.

| hard-v4, 96 cases (2 seeds x 48) | Solved | Wrong answers | No answer |
|---|---:|---:|---:|
| **Nemotron deep4 32K (swarm, own judge)** | **82** | 0 | 14 |
| DeepSeek 32K, 1 call | 85 | | |
| Nemotron single agent 32K | 54 | | |
| Hybrid (DeepSeek only on "no answer") | 88 | | 14 DeepSeek calls |

Seed 2 alone: Nemotron 41/48, DeepSeek 43/48. Paired over 96 cases: Nemotron +3 / -6 vs DeepSeek (two-sided sign test p = 0.51). Over two seeds Nemotron is 3 cases behind DeepSeek (82 vs 85), a difference the sign test cannot separate from noise; the Nemotron swarm still never answered wrongly, and the hybrid beats DeepSeek alone with 14 DeepSeek calls instead of 96.
