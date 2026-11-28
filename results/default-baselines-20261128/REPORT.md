# Current-default baseline aggregate

Descriptive results, verified locally on 2026-11-28 (Europe/Warsaw). No model calls, new experiment or default change.

All complete baseline cohorts named below are included. The outage-aborted hard-v33 segment is excluded; hard-v33 uses its complete valid rerun. Coding repeats the same 24 tasks with new sampling attempts, while arithmetic uses 48 tasks per corpus with two attempts each. These are attempt counts, not independent task counts.

| Domain / cohort | Cases | Solved | Wrong | Unanswered |
|---|---:|---:|---:|---:|
| swarm-baseline-hard26-v1 | 96 | 85 | 0 | 11 |
| swarm-baseline-hard27-v1 | 96 | 92 | 0 | 4 |
| swarm-baseline-hard28-v1 | 96 | 87 | 0 | 9 |
| swarm-baseline-hard29-v1 | 96 | 80 | 0 | 16 |
| swarm-baseline-hard30-v1 | 96 | 81 | 0 | 15 |
| swarm-baseline-hard31-v1 | 96 | 85 | 0 | 11 |
| swarm-baseline-hard32-v1 | 96 | 89 | 0 | 7 |
| swarm-baseline-hard33-v1 | 96 | 85 | 0 | 11 |
| swarm-baseline-hard34-v1 | 96 | 86 | 0 | 10 |
| swarm-baseline-hard35-v1 | 96 | 86 | 0 | 10 |
| swarm-baseline-hard36-v1 | 96 | 91 | 0 | 5 |
| coding-baseline-s52 | 72 | 67 | 5 | 0 |
| coding-baseline-s55 | 72 | 71 | 1 | 0 |
| coding-baseline-s61 | 72 | 70 | 2 | 0 |
| coding-baseline-s64 | 72 | 69 | 3 | 0 |
| coding-baseline-s79 | 72 | 70 | 2 | 0 |
| coding-baseline-s82 | 72 | 72 | 0 | 0 |
| coding-baseline-s85 | 72 | 68 | 4 | 0 |
| coding-baseline-v1 | 72 | 70 | 2 | 0 |
| coding-baseline-v2 | 72 | 69 | 3 | 0 |
| coding-baseline-v3 | 72 | 70 | 2 | 0 |
| **arithmetic total** | **1056** | **947** | **0** | **109** |
| **coding total** | **720** | **696** | **24** | **0** |

Arithmetic: 947/1,056 solved, 0 wrong over 11 hard sets (hard-v26 through hard-v36); mean 86.09/96 per set. Coding: 696/720 solved (96.67%), 24/720 wrong (3.33%), no unanswered cases across ten baseline cohorts.

The [machine-readable export](report.json) contains every case outcome and SHA256 hashes of the original local case, metadata and accounting inputs, plus coding worker summaries. Counts were recomputed from complete unique task/seed rows; every accounting record reports runner exit 0 and idle after completion. Arithmetic rows report no infrastructure failures or deadlines; coding selected outcomes also agree with the winner holdout records. Raw runs remain local; the public export supports recounting, not a new execution of the graders.

Cross-checks: the first five arithmetic and first six coding cohorts agree with the [night summary](../NIGHT_20261121_INKLING.md); the final four arithmetic and final three coding cohorts agree with its final baseline section and their individual reports. The hard-v31/v32 and coding s64 outcomes are included here so the headline uses every completed baseline, rather than only the previously summarized subset.

Policy scope: arithmetic roll12fair; coding R2 + code_elastic with cancel-on-accept. These baselines do not compare alternative methods or establish a new adoption.
