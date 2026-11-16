# DeepSeek V4.1 reference vs Nemotron agents on fresh tasks

Same fresh tasks and seeds (48 evaluation tasks x 3 seeds per corpus). Every success passes the exact verifier. Values are expected solved cases out of 144 for k independent attempts (average over all k-subsets). Bundled comparison: different model, checkpoint (DeepSeek is a custom abliterated checkpoint) and serving engine; DeepSeek uses all four Sparks for one TP4 model, Nemotron one Spark per replica. No wall-clock cutoffs.

## arithmetic-v2 (normal difficulty)

| Method | k=1 | k=2 | k=4 | k=8 | Mean completion tokens per attempt |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4.1 (1 call, 8K) | 144.0 | 144.0 | — | — | 902 |
| Nemotron original single call (8K) | 38.8 | 64.2 | 93.0 | — | 7,377 |
| Nemotron budget-forced agent (8K) | 123.1 | 136.2 | 141.4 | 144.0 | 4,905 |

## arithmetic-hard-v1

| Method | k=1 | k=2 | k=4 | k=8 | Mean completion tokens per attempt |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4.1 (1 call, 8K) | 98.5 | 107.0 | — | — | 4,408 |
| Nemotron original single call (8K) | 26.0 | 41.2 | 57.0 | — | 7,587 |
| Nemotron budget-forced agent (8K) | 27.9 | 44.4 | 63.2 | 81.0 | 6,986 |
| Nemotron deep agent (16K) | 53.0 | 76.8 | 99.0 | — | 12,418 |

