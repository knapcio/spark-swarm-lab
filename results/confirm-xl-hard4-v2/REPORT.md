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
