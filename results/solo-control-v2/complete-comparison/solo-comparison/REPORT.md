# Completed arithmetic quality comparison and stronger solo control

648 evaluation cases: 24 distinct tasks × 3 seeds × 9 methods. The first eight methods are the frozen primary study; sequential full-plan refinement is a separately frozen supplemental control. The task-cluster bootstrap uses 5,000 replicates, retaining all three seeds per task. These are 24 task clusters, not 72 independent problems.

| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Cascade: 32 short paths, then full plan | 36/72 | 50.0% | 34.7%–65.3% |
| Democracy: 32 agents | 15/72 | 20.8% | 6.9%–37.5% |
| Single full plan (8K) | 18/72 | 25.0% | 15.3%–34.7% |
| Two independent full plans | 36/72 | 50.0% | 36.1%–65.3% |
| Four independent full plans | 49/72 | 68.1% | 54.2%–80.6% |
| Independent: 100 short paths | 21/72 | 29.2% | 13.9%–47.2% |
| Independent: 32 short paths | 16/72 | 22.2% | 8.3%–37.5% |
| Shared frontier: 8 agents | 9/72 | 12.5% | 1.4%–26.4% |
| Sequential full-plan refinement | 45/72 | 62.5% | 47.2%–77.8% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| Cascade: 32 short paths, then full plan | 8424 | 509325 | 509325 | 72/72 | 69.245 / 83.156 |
| Democracy: 32 agents | 16672 | 271720 | 271720 | 72/72 | 17.176 / 30.904 |
| Single full plan (8K) | 72 | 516134 | 516134 | 72/72 | 68.945 / 74.154 |
| Two independent full plans | 144 | 790364* | 964324 | 72/72 | 86.694 / 96.295 |
| Four independent full plans | 288 | 993520* | 1631105 | 72/72 | 94.361 / 131.402 |
| Independent: 100 short paths | 23501 | 336352* | 337541 | 72/72 | 15.304 / 27.703 |
| Independent: 32 short paths | 8456 | 118991* | 120068 | 72/72 | 6.442 / 11.248 |
| Shared frontier: 8 agents | 2256 | 32725 | 32725 | 72/72 | 3.743 / 6.084 |
| Sequential full-plan refinement | 150 | 837867* | 980664 | 72/72 | 120.324 / 182.083 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Primary arithmetic plus separately frozen supplemental solo; shared task/seed labels enable descriptive paired contrasts. Separate execution schedules/source variants are retained; no causal or fleet-throughput inference.


## Paired stronger-solo contrast

Four independent full plans solve 49/72 (68.1%); sequential full-plan refinement solves 45/72 (62.5%). The paired four-plans-minus-refinement difference is +5.56 percentage points, with task-cluster 95% interval −5.56 to +16.67 points. This is a pointwise, unadjusted interval spanning zero; these data do not establish a reliable difference or an overall efficiency winner.

The primary producer is `cbcde299716b7842536b008880a089590e9816f8`; the supplemental solo producer is `a8adff19f690e90aec5705c373a82005e869f1f2`. Shared task/seed labels support descriptive paired comparisons, while separate execution schedules and source variants remain explicit. A shared seed does not guarantee an identical GPU sampling trajectory.

The recipes differ: full-plan groups can request multiple reasoning-ON 8K plans; short-path groups use reasoning-OFF 192-token actions. The sequential control can make up to four own-feedback full-plan attempts. This is a recipe comparison, not an isolated agent-count effect. Nominal case deadline is 180 seconds, with controller/cleanup overhead reflected in occupied case wall. Actual costs below are retained separately from budget ceilings.

| Method | Actual calls | Server input | Server output | Known server cases | Unfinished client calls |
|---|---:|---:|---:|---:|---:|
| Cascade: 32 short paths, then full plan | 8,424 | 1,026,895 | 509,325 | 72/72 | 0 |
| Democracy: 32 agents | 16,672 | 4,104,896 | 271,720 | 72/72 | 0 |
| Single full plan (8K) | 72 | 11,910 | 516,134 | 72/72 | 0 |
| Two independent full plans | 144 | 23,820 | 964,324 | 72/72 | 34 |
| Four independent full plans | 288 | 47,640 | 1,631,105 | 72/72 | 144 |
| Independent: 100 short paths | 23,501 | 2,815,532 | 337,541 | 72/72 | 521 |
| Independent: 32 short paths | 8,456 | 996,867 | 120,068 | 72/72 | 345 |
| Shared frontier: 8 agents | 2,256 | 273,359 | 32,725 | 72/72 | 0 |
| Sequential refinement (supplemental) | 150 | 30,842 | 980,664 | 72/72 | 27 |

All nine methods have complete server-counter coverage here. Client completion totals for unfinished calls remain lower bounds; the 144 unfinished ensemble-4 calls make its client-only token mean unsuitable for a cheaper-than-solo claim. Server totals include canceled work. Input and output tokens are separate measurements, not equal GPU-cost units.

These quality batches used four parallel job slots, one per replica, across an interleaved mixed-method queue. They measure occupied case latency and verified quality, not per-method saturated fleet throughput. See the separately scheduled [loaded four-node queue study](../../../throughput-timeoutguard-20261115/REPORT.md) for fixed-batch rates, queue waiting, and deadline effects.

[Machine-readable analysis](analysis.json), [paired contrasts](paired-deltas.csv), [per-task/seed pairs](paired-cases.csv), [provenance manifest](../manifest.json). Original coding grades and independent code confirmation remain separate and are not included in this arithmetic report.
