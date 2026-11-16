| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Four independent program chains | 376/384 | 97.9% | 93.0%–100.0% |
| Sequential program refinement | 237/384 | 61.7% | 21.4%–90.1% |

Training is charged once per frozen program, separate from graph evaluation.

| Method | Model calls | Client prompt / completion | Known server completion | Coverage |
|---|---:|---:|---:|---:|
| Four independent program chains | 64 | 247144 / 69935 | 69935 | 4/4 |
| Sequential program refinement | 64 | 289380 / 100120 | 100120 | 4/4 |

Fresh96 same-generator graphs; four paired frozen-program training seeds. Task-only intervals condition on frozen programs; crossed intervals resample graph and training-seed labels. All-pass bootstrap intervals can degenerate and do not imply true/general100% correctness. Original12 remain separate. Historical training charged once/program; zero additional model calls; remote CPU cost unknown.
