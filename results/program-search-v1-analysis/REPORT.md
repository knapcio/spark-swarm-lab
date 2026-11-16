# Original reusable-program experiment

Completed exploratory study: two methods × four paired training seeds = eight frozen selected programs. Each training episode spends 16 model calls scored on four development graphs, then freezes one program before testing all 12 evaluation graphs. There are 128 training calls and 96 program/graph evaluation records. This is a different representation and execution regime from direct assignment generation; it is not an isolated comparison of agent count.

| Method | Evaluation solved | Accuracy | Crossed graph/training-seed 95% CI | Task-only 95% CI, conditional on frozen programs |
|---|---:|---:|---:|---:|
| Four independent program chains | 47/48 | 97.9% | 87.5–100.0% | 93.8–100.0% |
| Sequential program refinement | 29/48 | 60.4% | 20.8–93.8% | 45.8–70.8% |

The 5,000-replicate crossed bootstrap resamples graph tasks and paired training-seed labels independently, sharing the draws across methods. The task-only interval holds the selected programs fixed. Four training seeds are a small empirical sample: 48 outcomes per method are not 48 independent tasks. The paired independent-minus-sequential difference is +37.5 percentage points, with a pointwise crossed interval +4.2 to +79.2 points. This broad interval describes this fixed corpus and four trained-program pairs; it does not establish a universal best method.

| Training seed | Four independent program chains | Sequential program refinement |
|---|---:|---:|
| 1 | 11/12 | 11/12 |
| 2 | 12/12 | 0/12 |
| 3 | 12/12 | 10/12 |
| 4 | 12/12 | 8/12 |

## Training cost is charged once per selected program

| Method | Selected programs | Model calls | Actual server input tokens | Actual server output tokens | Known server episodes |
|---|---:|---:|---:|---:|---:|
| Four independent program chains | 4 | 64 | 247,144 | 69,935 | 4/4 |
| Sequential program refinement | 4 | 64 | 289,380 | 100,120 | 4/4 |

Both methods have complete client responses/usage and known exclusive server-counter costs for all four training episodes. Do not multiply training calls/tokens by the 12 evaluation graphs. CPU grading is additional work: per-episode grading wall and container limits are retained in the JSON; remote solver CPU time is unknown and remains null. Mixed master wall includes qualification, scheduling, parallel episodes and drain, so it is not per-method fleet throughput. Equal call ceilings do not imply equal consumed tokens or GPU cost.

## Exact checks and provenance

All 96 original evaluation records were checked against frozen selected-source hashes and the original graph IDs. There are 78 returned-assignment proofs: 76 exact passes and two graph failures. The remaining 18 records have no returned-assignment proof: 16 candidate runtime failures and two candidate timeouts, all retained as unsolved in the denominator. Each available proof was independently recomputed with the exact outer graph verifier. No generated code was executed during this offline report.

The traces preserve selection before evaluation, no model calls after selection, and all 128 request/response IDs. Every grade retains outer-parent authority, no oracle sent to child, and successful cleanup. Four initial model-endpoint drains, all eight final episode drains, runtime identity, before/after source identity, and all 12 frozen file hashes against Git source `c5ed1190ac380cf1ed1193b0bd7971dcc0eb1bae` were verified. The raw data and original program sources remain unchanged.

This report covers the original program experiment only. The newly requested independent CPU confirmation and later format controls are separate datasets and do not replace these results.

- [Statistics JSON](programs/analysis.json), [summary CSV](programs/summary.csv), [paired contrasts](programs/paired-deltas.csv), [training costs](programs/training-costs.csv)
- [Crossed-interval chart PNG](programs/accuracy-crossed95.png), [SVG](programs/accuracy-crossed95.svg)
- [Audit receipt](audit.json), [source/input/output hash manifest](manifest.json), [all eight lineage DAGs](lineage-index.json)
