# XXL: thinking-budget scaling for deep4 (arithmetic-hard-v3, seed 1)

Plan `XXL_HARD3_PLAN.json` (frozen before any xxl call; erratum v1 -> v2 for a 1800 s per-request limit; amendments 1-2 = continuations after my overload of the servers). Agent `xxl_forced_original` = deep agent with thinking cap 61440 / total 65536 on the 128K serving clones. Same 48 tasks and seed as the 16K and 32K runs; same arbiter-free judge selection. Merged from {'xxl-hard3-seed1-v2': 11, 'xxl-hard3-seed1-v2b': 11, 'xxl-hard3-seed1-v2c': 26} (earliest completed record per case).

| Budget per agent (total) | deep4 solved / 48 | single agent (agent 0) | wrong answers | no answer | tokens / case |
|---|---:|---:|---:|---:|---:|
| 16K | 31 | 19 | 0 | | 58,900 |
| 32K | 38 | 23 | 0 | | 90,649 |
| **64K** | **38** | **29** | 0 | 10 | 132,982 |
| DeepSeek 32K, 1 call | 39 | | | | |

Paired 64K vs 32K: +2 / -2. 64K vs DeepSeek: +2 / -3. Hybrid (DeepSeek only on 64K abstentions): 41/48 with 10 DeepSeek calls. Oracle any-of-4: 38/48.

Reading: the single agent keeps improving with budget (19 -> 23 -> 29 of 48), but the 4-agent swarm saturates at 38/48 from 32K on, the same as DeepSeek's 39; even any-of-4 is 38. On this set the remaining ~10 tasks are not reached by more thinking or by four agents; 32K is the efficient point for the swarm, 64K mainly makes a single agent cheaper to rely on (29/48 alone). Zero wrong answers at every budget.
