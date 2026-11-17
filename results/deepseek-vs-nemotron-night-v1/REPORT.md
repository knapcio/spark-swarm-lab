# DeepSeek V4.1 vs the best Nemotron configurations (night of 16-17 Nov 2026)

Same fresh evaluation tasks for both models. DeepSeek: native pico/dsgb10 TP4 on all four Sparks, custom abliterated V4.1-Flash-1017 checkpoint, frontend default effort ("high"), streamed, no wall-clock cutoff. Nemotron: one replica per Spark, independent agents, no communication. Bundled comparison (model, checkpoint, engine, hardware use differ); not equal compute.

## Hard arithmetic (arithmetic-hard-v1 evaluation, 48 tasks x 3 seeds = 144)

| Method | Solved / 144 | Completion tokens per case |
|---|---:|---:|
| DeepSeek, 1 call, 8K cap (81/288 calls truncated) | 98.5 (expected) | ~4.4K |
| DeepSeek, 2 calls, 8K cap | 107 | ~8.8K |
| **DeepSeek, 1 call, 32K cap** (14/144 still hit 32K, all failed) | **115** | 9.1K |
| Nemotron, original method, 4 calls | 57 | ~30K |
| Nemotron, 8 budget-forced 8K agents | 81 | 55.9K |
| Nemotron, 4 deep 16K agents | 99 (98 strict) | 49.7K |
| **Nemotron, 8 deep 16K agents** | **111 (110 strict)** | 100.4K |
| Nemotron, escalation 4 short then 4 deep (offline simulation from two runs) | 107 | 58.4K |

## Hard coding (coding-hard-v1 evaluation, 24 tasks x 3 seeds = 72; holdout-scored)

| Method | Solved / 72 |
|---|---:|
| Nemotron, original single call | 4 |
| Nemotron, 8 budget-forced 8K agents (selection by feedback tests) | 28 |
| Nemotron, 8 deep 16K agents | 37 |
| **DeepSeek, 1 call, 32K cap** (5/72 hit the cap) | **61** |

## Reading

- On hard arithmetic, where an exact verifier (or Nemotron's own thinking judge, 0 false accepts in 2,282 checks) can pick the winner, eight deep Nemotron agents come within a few cases of one uncapped DeepSeek call, at roughly 11x the completion tokens.
- On hard coding the gap is large: one DeepSeek call solves 61/72, the best Nemotron swarm 37/72. More or deeper Nemotron agents flatten out (4 deep 34, 8 deep 37), so the missing capability is not recovered by sampling.
- The earlier 8K DeepSeek numbers understated DeepSeek: a quarter of its hard arithmetic calls were cut off.

Sources: runs/deepseek-hard-32k-v2 (the first 32K launch, runs/deepseek-hard-32k-v1, was stopped after an inherited 480 s deadline killed calls; diagnostic only), runs/deepseek-coding-v1, results/confirm-hard-*, results/coding-hard-*, results/night-audit-20261117/AUDIT.md.
