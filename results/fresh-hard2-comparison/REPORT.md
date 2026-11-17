# Fresh hard tasks: arbiter-free Nemotron swarm vs DeepSeek (arithmetic-hard-v2, seed 1, 48 tasks)

Both plans frozen before the corpus existed. DeepSeek: one call, 32K cap, default effort. Nemotron: the frozen arbiter-free swarm (4 short agents + judge, escalation to 4 deep agents + judge). Exact verifier scores only.

| | DeepSeek, 1 call | Nemotron arbiter-free swarm |
|---|---:|---:|
| Solved / 48 | **39** | **30** |
| Wrong answers | 3 (finished but invalid) + 6 cut at 32K | 0 (+18 "no answer") |
| 4-number tasks solved / 24 | 24 | 22 |
| 6-number tasks solved / 24 | 15 | 8 |
| Completion tokens per task | 8,706 | 77,633 |

Paired by task: both solved 29, only DeepSeek 10, only Nemotron 1. Over all 3 seeds the Nemotron swarm solved 96/144 (67%) with 0 wrong answers.

Reading: on fresh hard tasks DeepSeek in one call stays clearly ahead (≈81% vs ≈63%); the Nemotron swarm is fully reliable when it answers (no wrong answers) but abstains on about a third, mostly 6-number tasks, while spending about 9x the tokens.
