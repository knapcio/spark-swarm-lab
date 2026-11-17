# Live hybrid on fresh hard tasks (arithmetic-hard-v3): Nemotron swarm first, DeepSeek only on "no answer"

Rule frozen before hard-v3 existed (HYBRID_HARD3_DEEPSEEK_PLAN.json): the arbiter-free Nemotron board2x2 swarm answers when its thinking judge accepts a plan; DeepSeek (1 call, 32K) is called only for the cases where the swarm gave no answer. DeepSeek was also run on every seed-1 task as a stand-alone baseline.

All 144 cases (48 tasks x 3 seeds):

| System | Solved / 144 | DeepSeek calls |
|---|---:|---:|
| Nemotron board2x2 swarm alone | 98 (0 wrong, 46 no answer) | 0 |
| **Hybrid: swarm, then DeepSeek on "no answer"** | **120** | 46 |

DeepSeek solved 22/46 of the cases the swarm abstained on.

Seed 1 (48 tasks), where DeepSeek alone was also measured:

| System | Solved / 48 | DeepSeek calls |
|---|---:|---:|
| DeepSeek alone | 39 | 48 |
| Nemotron swarm alone | 32 | 0 |
| **Hybrid** | **40** | 16 |

Mean DeepSeek completion tokens per call: 11,936. Errors [].
