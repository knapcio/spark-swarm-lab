| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Four independent program chains | 47/48 | 97.9% | 87.5%–100.0% |
| Sequential program refinement | 29/48 | 60.4% | 20.8%–93.8% |

Training is charged once per frozen program, separate from graph evaluation.

| Method | Model calls | Client prompt / completion | Known server completion | Coverage |
|---|---:|---:|---:|---:|
| Four independent program chains | 64 | 247144 / 69935 | 69935 | 4/4 |
| Sequential program refinement | 64 | 289380 / 100120 | 100120 | 4/4 |

Four-training-seed-limited exploratory intervals. Task-only CI is conditional on frozen programs; crossed bootstrap includes empirical training-seed variation. Forty-eight graph/seed outcomes are not independent tasks.
