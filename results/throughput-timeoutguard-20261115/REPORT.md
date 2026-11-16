# Completed four-node throughput study

All 45 corrected cohorts passed the final gate: 36 development batches and 9 evaluation batches. This report describes one fixed arithmetic corpus and one four-node serving recipe. It does not establish a universal best swarm method.

**Concurrency:** `j` means admitted concurrent task cases **per node**. It is neither the number of agents nor the number of active server sequences. Four replicas each retain a 25-sequence engine cap. A logical group may contain 8, 32, or 100 agents while requests queue behind that cap.

## Evaluation: fixed development-selected concurrency

Each row is a fresh batch of 24 distinct evaluation tasks × 4 seeds = 96 attempts across the same four Sparks. Successful attempts/minute divides verified successful seeded attempts by the measured full batch wall, including scheduling and final drain. These are repeated attempts on 24 tasks, not 96 independent problems.

| Method | j/node | Solved | Accuracy; task-cluster 95% CI | Batch wall s | Successful attempts/min |
|---|---:|---:|---:|---:|---:|
| Single full plan (8K) | 8 | 33/96 | 34.4%; 21.9–46.9% | 512.26 | 3.87 |
| Sequential refinement (up to 4 plans) | 8 | 35/96 | 36.5%; 25.0–47.9% | 541.78 | 3.88 |
| Two independent full plans | 8 | 36/96 | 37.5%; 27.1–49.0% | 541.03 | 3.99 |
| Four independent full plans | 4 | 48/96 | 50.0%; 35.4–64.6% | 1002.88 | 2.87 |
| Cascade: 32 short paths, then full plan | 8 | 35/96 | 36.5%; 22.9–51.0% | 500.55 | 4.20 |
| Independent: 32 short paths | 1 | 22/96 | 22.9%; 8.3–39.6% | 150.77 | 8.76 |
| Independent: 100 short paths | 4 | 30/96 | 31.2%; 14.6–49.0% | 347.59 | 5.18 |
| Democracy: 32 agents | 2 | 18/96 | 18.8%; 5.2–34.4% | 397.43 | 2.72 |
| Shared frontier: 8 agents | 8 | 12/96 | 12.5%; 2.1–25.0% | 33.79 | 21.31 |

The 95% intervals use 5,000 task-cluster bootstrap replicates, retaining all four seeds for each resampled task. Each batch has one observed wall time, so no throughput-rate confidence interval is inferred. Shared frontier has the highest observed rate here, with 12/96 successes in a short 33.79-second batch; four full plans solve 48/96 at a lower observed rate. These are different quality, latency, and cost tradeoffs.

## Development selection

The tested grid stops at j=8 admitted cases per node; this is not proof that j=8 is globally optimal or that the 25-sequence engine cap was continuously saturated. Each cell is successful seeded attempts/minute on 8 development tasks × 4 seeds. The frozen rule maximizes that rate, choosing the smaller j when within 1% of the maximum. Recomputing all 36 rows exactly reproduced all nine frozen choices; the input ledger-prefix hash and selection-before-evaluation timestamps also matched.

| Method | j1 | j2 | j4 | j8 | Selected j |
|---|---:|---:|---:|---:|---:|
| Single full plan (8K) | 1.98 | 2.21 | 2.14 | 4.11 | 8 |
| Sequential refinement (up to 4 plans) | 1.45 | 1.70 | 2.66 | 3.32 | 8 |
| Two independent full plans | 1.95 | 1.98 | 3.07 | 4.31 | 8 |
| Four independent full plans | 1.93 | 2.66 | 3.66 | 3.30 | 4 |
| Cascade: 32 short paths, then full plan | 2.30 | 3.21 | 4.74 | 6.31 | 8 |
| Independent: 32 short paths | 12.95 | 11.75 | 11.56 | 12.03 | 1 |
| Independent: 100 short paths | 4.33 | 4.03 | 4.78 | 4.16 | 4 |
| Democracy: 32 agents | 2.90 | 4.00 | 3.24 | 3.32 | 2 |
| Shared frontier: 8 agents | 15.95 | 17.14 | 22.16 | 30.65 | 8 |

## Queueing and deadlines

Values below are median / p95 seconds across all 96 cases, including unsolved cases. Queue wait runs from common queue start to admission; service begins at admission; total ends at case completion. These quantiles are descriptive, not confidence intervals. The nominal case budget is 180 seconds **after admission**. The HTTP request timeout is 210 seconds, with controller observation every 0.1 seconds plus termination/drain overhead. Waiting time therefore does not consume the nominal case budget.

| Method | Queue wait | Service after admission | Total since queue start |
|---|---:|---:|---:|
| Single full plan (8K) | 175.63 / 359.52 | 165.04 / 180.10 | 304.87 / 492.28 |
| Sequential refinement (up to 4 plans) | 180.12 / 360.18 | 180.03 / 180.11 | 309.82 / 520.89 |
| Two independent full plans | 180.09 / 360.21 | 180.03 / 180.10 | 319.47 / 540.18 |
| Four independent full plans | 360.16 / 783.02 | 174.60 / 180.09 | 522.51 / 871.61 |
| Cascade: 32 short paths, then full plan | 180.17 / 360.37 | 180.02 / 180.16 | 267.91 / 492.80 |
| Independent: 32 short paths | 65.82 / 126.93 | 5.13 / 8.85 | 70.81 / 134.65 |
| Independent: 100 short paths | 124.49 / 289.50 | 48.59 / 83.51 | 165.10 / 318.97 |
| Democracy: 32 agents | 160.52 / 345.39 | 25.45 / 44.64 | 193.61 / 369.52 |
| Shared frontier: 8 agents | 10.98 / 26.06 | 8.29 / 14.28 | 19.70 / 32.95 |

## Actual server work

All nine evaluation batches have known four-node global prompt/completion counter deltas, captured after final drain. The counters include work from responses canceled after a verified solution or deadline. Client usage can be incomplete for canceled calls; missing client infrastructure counts are unknown, not proof of zero failures. Global token counts describe measured work and are not interchangeable GPU-cost units. Output tokens/second below divides global completions by full queue wall; it is a fleet end-to-end rate, not per-stream decode speed.

| Method | Server input tokens | Server output tokens | Fleet output tokens/s | Unfinished client calls | Client infrastructure count unknown cases |
|---|---:|---:|---:|---:|---:|
| Single full plan (8K) | 15,880 | 656,563 | 1281.71 | 28 | 28 |
| Sequential refinement (up to 4 plans) | 23,523 | 693,330 | 1279.72 | 61 | 61 |
| Two independent full plans | 31,760 | 1,048,749 | 1938.44 | 151 | 94 |
| Four independent full plans | 63,520 | 1,870,724 | 1865.35 | 322 | 93 |
| Cascade: 32 short paths, then full plan | 1,366,529 | 617,036 | 1232.71 | 50 | 50 |
| Independent: 32 short paths | 1,323,515 | 158,373 | 1050.44 | 468 | 22 |
| Independent: 100 short paths | 3,651,563 | 436,554 | 1255.95 | 750 | 30 |
| Democracy: 32 agents | 5,568,640 | 365,824 | 920.47 | 0 | 0 |
| Shared frontier: 8 agents | 364,552 | 43,752 | 1294.78 | 0 | 0 |

## Protocol and provenance

The full-plan methods use reasoning ON and up to 8,192 completion tokens per call. Short-path methods use reasoning OFF and 192-token calls; the cascade can fall back to a long reasoning plan. A common 32,768-token case ceiling does not make actual input/output usage equal. This comparison varies complete recipes, not agent count in isolation. Direct and iterative solo also use all four replicas, solving different task cases concurrently.

The four cheap-policy arms (independent 32, independent 100, democracy 32, shared frontier 8) are a later exploratory coverage amendment designed after primary seed-1 inspection. Their development selection was still frozen before these throughput evaluation batches.

All 45 cohorts use source `7bb965b073af8cdc211404186c15463d5cfc374e` and runtime SHA `072b628126f36aa559fa864372118c7e0497e44d1b37d29be99ea3c7f8cf6ec5`. The timeout amendment changes transport timeout and instrumentation metadata to avoid a 180-second HTTP timer racing the 180-second case controller. Model, prompts, method policies, and token budgets remain unchanged. The earlier four throughput diagnostic cohorts are preserved separately and excluded from these 45.

The low-load quality/control comparison is a separate execution regime: [complete primary plus stronger solo control](../solo-control-v2/complete-comparison/solo-comparison/REPORT.md). Its case timings cannot be treated as per-arm fleet throughput from mixed-arm queue wall times. Under load, direct/refinement full-plan cases frequently approach the fixed deadline; differences from the low-load control table should retain that context.

No raw benchmark files or model outputs were edited. No raw trace archive is included at this stage. Derived JSON retains original local provenance paths; the manifest records exact source/input/output hashes and CLI arguments.

- [Evaluation CSV](evaluation/summary.csv), [JSON](evaluation/summary.json)
- [Development CSV](development/summary.csv), [recomputed selection](development/selection.json)
- [Frozen input snapshots](input-snapshots/), [source/drain provenance](provenance.json), [hash manifest](manifest.json)
- [Development chart](figures/development-throughput.png), [evaluation quality/rate](figures/evaluation-throughput-success.png), [latency](figures/evaluation-latency.png), [server costs](figures/evaluation-global-cost.png)
