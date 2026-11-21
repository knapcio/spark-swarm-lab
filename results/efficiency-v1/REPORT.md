# Efficiency: Inkling-2-Mini fleet vs DeepSeek V4.1 on the same four Sparks (GPU energy, tasks per hour)

Plan `EFFICIENCY_PLAN.json` (frozen in 5b1d3bf before any measurement). Fable idea #6 (energy per solved task).

## Measured throughput and GPU-rail energy (synthetic thinking workload, max_tokens 4096, one batch per arm)

| Arm | Concurrency | Fleet completion tok/s | GPU-rail J per token | Mean GPU power per node |
|---|---:|---:|---:|---:|
| Inkling, four replicas (one per Spark) | 24 per node | **1412** | **0.083** | ~29 W |
| DeepSeek V4.1 Flash, TP4 on all four Sparks | 8 | 216 | 0.560 | ~30 W |
| DeepSeek V4.1 Flash, TP4 on all four Sparks | 16 (all slots) | 276 | 0.441 | ~30 W |

DeepSeek was measured after an unscored warm-up batch (first run after a boot is slow). Both models draw about the same GPU
power (~30 W per Spark: decoding is memory-bound), so energy per token follows throughput: the Inkling fleet produces
5.1x the tokens per second of DeepSeek's best measured concurrency and needs 5.3x less GPU energy per token.

## Derived cost per solved task

Tokens per case and solve rates from the frozen quality runs (hard-v4 96 cases, coding-hard 72, bugbench 36), times the
measured fleet rates above. "One Inkling" = four independent replicas each working on different tasks.

| Task family | System | Completion tokens / case | Solve rate | Solved tasks per hour (whole fleet) | GPU Wh per solved task |
|---|---|---:|---:|---:|---:|
| Hard arithmetic | One DeepSeek | 6,486 | 0.89 | 136 | 0.90 |
| Hard arithmetic | One Inkling | 15,285 | 0.72 | 239 | 0.49 |
| Hard arithmetic | Inkling swarm (4 + judge) | 61,642 | 0.94 | 77 | 1.51 |
| Hard coding | One DeepSeek | 12,229 | 0.85 | 69 | 1.77 |
| Hard coding | One Inkling | 12,736 | 0.86 | 344 | 0.34 |
| Hard coding | Inkling swarm (8) | 101,889 | 0.96 | 48 | 2.44 |
| Bug fixing | One DeepSeek | 2,786 | 1.00 | 357 | 0.34 |
| Bug fixing | One Inkling | 6,642 | 1.00 | 765 | 0.15 |
| Bug fixing | Inkling swarm (8) | 60,885 | 1.00 | 83 | 1.40 |

Reading: with Inkling the economics flip. A single Inkling agent matches DeepSeek on coding (62 vs 61/72) and bug fixing
(36/36) and, run as four replicas, solves about 5x more coding tasks per hour at about one fifth of the GPU energy. On hard
arithmetic one Inkling is weaker (69 vs 85/96) but still cheaper per solved task; the Inkling swarm is the most accurate
system measured (90/96 arithmetic, 69/72 coding) and costs more GPU energy per solved task than One DeepSeek on all three families: accuracy, not
cost, is what the swarm buys now.

Limits: GPU rail only (`nvidia-smi power.draw`; CPU, memory, NIC, SSD, fans and PSU losses not measured); one batch per arm
on a synthetic workload whose length distribution differs from the evaluation tasks; derived rows assume the fleet runs at
the measured saturated throughput (latency per request is lower for DeepSeek: ~24 vs ~18 tok/s at full load); DeepSeek runs
its production engine with its own speculative decoding, Inkling the SGLang DSpark recipe.
