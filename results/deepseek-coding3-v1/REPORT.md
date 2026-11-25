# deepseek-coding3-v1: One DeepSeek vs the Inkling coding swarm

Status: complete

| system | status | solved | wrong | unanswered |
|---|---|---|---|---|
| DS | complete | 57/72 | 0 | 15 |
| R2 | complete | 67/72 | 4 | 1 |
| R1 | complete | 66/72 | 6 | 0 |

## Paired (exact sign test)

- DS_vs_R2: DS-only solved 1, swarm-only 11, p = 0.006348
- DS_vs_R1: DS-only solved 4, swarm-only 13, p = 0.04904

## Hybrid: swarm first, DeepSeek on the swarm's unanswered cases

- R2+DS: solved 67/72, wrong 4, DS calls 1
- R1+DS: solved 66/72, wrong 6, DS calls 0

## Cost

- DS: client completion tokens per case 12,497.9, run wall 4,422.5 s, GPU 150.3 Wh, Wh per solved 2.637
- R2: server generated tokens per case 29,250.0, wall 3,541.8 s, GPU 89.2 Wh, Wh per solved 1.332
- R1: server generated tokens per case 19,676.7, wall 4,588.2 s, GPU 87.2 Wh, Wh per solved 1.321

Bundled differences (model, engine, one call vs a swarm); no causal model-size claim. DS tokens are client-side completion tokens; the swarm figures are server counters.
