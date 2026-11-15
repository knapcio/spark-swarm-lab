# Evaluation progress — runtime-v2 restart, aggregate pending

The [runtime-v2 amendment](RUNTIME_V2_AMENDMENT.json) requires **all 900 primary cases** to execute fresh under the qualified v0.32.0 serving image: 576 arithmetic cases (24 tasks × 8 arms × 3 seeds) and 324 coding cases (18 tasks × 6 arms × 3 seeds), plus a separate 80 supplementary solo attempts. **No runtime-v1 or partial rows, including the original arithmetic seed 1 below, are pooled into v2.** Earlier reports remain public historical/diagnostic records. Prior v1 outcomes were already inspected; the disclosed infrastructure amendment leaves the preselected methods, prompts, datasets, seed lists and budgets unchanged.

The [single-node qualification evidence](SERVING.md) and [141-artifact export](results/serving-v032-20261115/manifest.json) cover matched c25 repeats, old/new diagnostic replays, short-JSON/tool probes and a reasoning-on exact-plan smoke. The observed +1.60% median serving difference is not a robust speedup or proven crash fix. At this qualification stage, fleet deployment remains pending; v2 generation is gated on four healthy idle replicas with exact runtime/source pins. Frozen source tags are `evaluation-runtime-v2` (`114e17f`), `solo-control-runtime-v2` (`2825e5f`) and `throughput-runtime-v2` (`216a9f3`).

## Preserved runtime-v1 arithmetic seed 1

This is an interim record for [spark-swarm-lab](https://github.com/knapcio/spark-swarm-lab). Only the first completed **arithmetic** cohort is reported here: **24 evaluation tasks × 8 frozen arms = 192 cases**, seed 1. The final three-seed, task-clustered aggregate is pending. These observations do not select or change a method, prompt, budget or configuration, and no winner is declared.

## Frozen protocol and scope

The [selection record](EVALUATION_SELECTION.json) was frozen at **2026-11-15 14:05:32 UTC**, before this cohort started at **14:07:45 UTC**. Producer source: `736ee1e9ab4a1b1ef534be587fe967c307c485e6`. The seven captured source hashes match both the final hashes and the frozen producer files. Public dataset SHA-256: `434830c439ceb286947d373df9bea1dff60da28aa83f9164e4335be4f6658398`.

Each case has a 1280-call / 32,768-completion-token ceiling, five rounds and a 180-second controller deadline. Full-plan thinking uses an 8192-token response cap; cheap step calls use 192, temperature 0.8. Cascade 32 first tries cheap independent rounds and, if unsolved, one original-task full plan. Democracy includes the preselected exact-target guard. Stop-on-verified-solution and server-counter capture are enabled.

Four persistent job slots each own one Spark/endpoint. A task's rotated arms run sequentially on its assigned node, with at most 25 simultaneous requests per endpoint. N100 is a logical path count that includes queued calls. This measures task-solving quality, occupied case latency and observed costs; **it is not a saturated-fleet throughput comparison**. Whole mixed-arm queue wall was **2187.770924 seconds** and cannot be assigned to individual arms.

## Interim arithmetic results

Every denominator below is 24 tasks at seed 1. Wilson intervals describe this one seed's task outcomes only; the final report will retain all seeds within task clusters rather than treating 72 repeated task/seed cases as 72 independent tasks. Case wall includes controller, metrics and drain overhead, and is measured across all cases, not only successes.

| Arm | Solved | Wilson 95% | Median wall s | p95 wall s | Length finishes |
|---|---:|---:|---:|---:|---:|
| Direct (thinking on, 8k) | 8/24 | 18.0–53.3% | 66.742 | 70.974 | 16 |
| Full-plan ensemble 2 (on, 8k) | 9/24 | 21.2–57.3% | 87.384 | 93.408 | 28 |
| Full-plan ensemble 4 (on, 8k) | 15/24 | 42.7–78.8% | 84.782 | 129.918 | 36 |
| Independent 32 | 7/24 | 14.9–49.2% | 5.493 | 9.831 | 0 |
| Independent 100 | 10/24 | 24.5–61.2% | 14.748 | 25.527 | 1 |
| Democracy + guard 32 | 4/24 | 6.7–35.9% | 16.960 | 28.971 | 3 |
| Shared memory 8 | 3/24 | 4.3–31.0% | 3.609 | 6.456 | 1 |
| Cascade 32 then direct (on, 8k) | 13/24 | 35.1–72.1% | 63.092 | 78.982 | 15 |

Length finishes count capped responses, not independently proven incorrect answers. Full raw outputs, failed attempts and partial traces remain in the export. The single seed and fixed synthetic construction distribution limit generalization; statistical comparisons across all planned seeds have not been run.

## Cost accounting

The controller can terminate siblings after one verified solution. Completed-client usage then omits unfinished work; starred client prompt/output totals are **lower bounds**. Calls count dispatched `request_start` events, including requests whose final response was cancelled. Server snapshots and idle/drain checks were independently recomputed and are valid for **24/24 cases in every arm, 192/192 overall**; server totals below therefore cover this entire cohort. No unknown server case is replaced with zero.

| Arm | Calls | Client prompt | Client completion | Unfinished calls | Server prompt | Server completion |
|---|---:|---:|---:|---:|---:|---:|
| Direct (on, 8k) | 24 | 3,970 | 176,475 | 0 | 3,970 | 176,475 |
| Full-plan ensemble 2 | 48 | 6,469* | 268,976* | 9 | 7,940 | 304,030 |
| Full-plan ensemble 4 | 96 | 8,419* | 352,677* | 45 | 15,880 | 525,569 |
| Independent 32 | 2751 | 317,410* | 38,535* | 150 | 320,630 | 38,929 |
| Independent 100 | 7603 | 899,435* | 109,697* | 250 | 905,545 | 110,376 |
| Democracy + guard 32 | 5696 | 1,435,232 | 93,253 | 0 | 1,435,232 | 93,253 |
| Shared memory 8 | 752 | 91,187 | 11,356 | 0 | 91,187 | 11,356 |
| Cascade 32 | 2727 | 333,157 | 158,929 | 0 | 333,157 | 158,929 |

Input and output tokens are distinct accounting quantities, not equal GPU-cost units. The output-cost figure uses completed-client usage and marks lower bounds; use the server columns when assessing cancelled work. No case deadline, budget denial or controller error was recorded. Completed worker `run_end` records report zero infrastructure failures; **41 early-stopped cases have no final worker infrastructure count**, which remains unknown rather than being interpreted as a confirmed zero.

## Independent proof and provenance audit

The [audit artifact](results/evaluation-v1/arithmetic-s1/analysis/proof-cost-audit.json) and [audit script](results/evaluation-v1/arithmetic-s1/analysis/proof-cost-audit.py) record:

- **16,035 legal transitions** independently replayed using `Fraction`, preserving ordered state consumption, distinct indices and positive integer intermediate values; **403 illegal proposals** independently rejected.
- **305 root states** checked against their public task. All completed full-plan responses were checked for bounded move arrays and execution from their own original root; traced actions match the returned plan prefix. Invalid or truncated responses remain unsuccessful data.
- **128 successful reward events** checked for exact target presence and a fully replayed legal ancestry. These are successful paths/rewards, not 128 independently solved tasks. Every one of the **69 controller stops** has an earlier producer proof; the controller event is never its own proof.
- **19,697 request starts / 19,243 request ends** checked for globally unique IDs, matching request contexts, and exact summary usage, charges, errors, length finishes and budget denials. All server known flags and deltas were recomputed from raw snapshots.
- All 192 planned task/arm/seed cases, frozen arm settings, source pins, dataset hash and pre-run selection timing verified. The public task records contain only ID, split, numbers and target. Pinned runner/harness source and command/config inspection found no reference-witness or reputation input; the private reference-witness file was not opened for this audit.

The [export manifest](results/evaluation-v1/arithmetic-s1/manifest.json) covers **590 artifacts** with original/export SHA-256 and exact path/interpreter normalizations. Its schema-2 inverse audit preserves parsed values/order/types while allowing JSON/CSV formatting changes. Model/source values and script/figure bytes remain unchanged. Analysis hashes retain provenance to the original metadata and summary. No raw trace was edited and no model API was called during this audit or curation.

## Figures and data

![Evaluation arithmetic seed 1 of 3, aggregate pending](results/evaluation-v1/arithmetic-s1/analysis/accuracy-wilson95.png)

![Evaluation seed 1 client-output cost; starred costs are lower bounds](results/evaluation-v1/arithmetic-s1/analysis/success-vs-completion-cost.png)

[192-case CSV](results/evaluation-v1/arithmetic-s1/summary.csv) · [JSON](results/evaluation-v1/arithmetic-s1/summary.json) · [metadata/source pins](results/evaluation-v1/arithmetic-s1/metadata.json) · [analysis](results/evaluation-v1/arithmetic-s1/analysis/analysis.json) · [paired task outcomes](results/evaluation-v1/arithmetic-s1/analysis/paired-results.csv) · [accuracy SVG](results/evaluation-v1/arithmetic-s1/analysis/accuracy-wilson95.svg) · [cost SVG](results/evaluation-v1/arithmetic-s1/analysis/success-vs-completion-cost.svg) · [latency SVG](results/evaluation-v1/arithmetic-s1/analysis/case-latency.svg).

The table above remains a separate historical v1 report. New v2 cohorts will be reported only after completion, validity-ledger review and audit, with full task-clustered aggregation after all 900 valid primary cases. The separate supplementary solo-refinement protocol was requested before evaluation outcomes and is not included in this historical table. This progress report does not change method selection.

## Coding instrumentation repair and cohort validity

The entire original **108-case coding seed-1 cohort** is retained as diagnostic data and **excluded from primary aggregation**. A controller process-exit race and grader classification of unbounded-memory candidate processes required instrumentation repairs. The uniform instrumentation rerun was prepared from source `6c9dfe8` for all three coding seeds; the subsequent serving failure led to the complete runtime-v2 restart described above. Every arm and task is retained rather than selecting failed cases. Model policies, datasets, prompts and budgets are unchanged. This note records the validity decision, not new coding scores or a winner claim.

Published repair tags are `evaluation-infra-v1`, `solo-control-infra-v1` and `throughput-infra-v1`. Final aggregation must use the maintained cohort ledger with `aggregate_evaluation.py --ledger ...`: excluded/invalid entries are rejected, and each included entry must confirm matching domain/seed/source, completed case count, successful completion and unchanged sources. Fixed coding directory names are accepted explicitly by ledger identity; curated aliases resolve their original identity through their export manifest. Missing server cost remains unknown, and all task seeds remain together in the final task-cluster bootstrap.

### Original coding seed 1: diagnostic preservation only

The complete original 108-case cohort is preserved in [diagnostics-instrumentation-v1/coding-s1](results/diagnostics-instrumentation-v1/coding-s1/), with [explicit exclusion and typed fault evidence](results/diagnostics-instrumentation-v1/coding-s1/diagnostic-validity.json) and an [integrity manifest](results/diagnostics-instrumentation-v1/coding-s1/manifest.json). All **327 original artifacts** remain represented; original/export SHA-256 and semantic re-export checks pass. Historical metadata, outcomes, model code, grades and original error classifications are not rewritten.

The two fault classes remain distinct: one owned-process exit race (`PermissionError`, final controller return code missing despite a completed producer), and two candidate exits 137 originally classified as grader infrastructure errors. The main researcher's inspection of the generated function shows a non-advancing loop: `i=j` with `j=i`. The traces independently confirm exit 137, but the old `--rm` grader retained no kernel OOM flag. This is consistent with candidate memory exhaustion, **not kernel-proven historical OOM**. The recorded cleanup flags are true. Across all 108 cases, request/usage reconciliation matches **650 starts, 645 ends and five unfinished calls**. This is a preservation audit, without an accuracy table or arm ranking. The entire cohort stays excluded; the uniform replacement is not limited to the affected cases.

### Original arithmetic seed 2: diagnostic preservation only

The complete original **192-case arithmetic seed-2 cohort** is also excluded from primary aggregation and preserved in [diagnostics-instrumentation-v1/arithmetic-s2](results/diagnostics-instrumentation-v1/arithmetic-s2/). Its captured start/end sources match, no job slot failed, and the original controller exited 1. The [typed validity record](results/diagnostics-instrumentation-v1/arithmetic-s2/diagnostic-validity.json) preserves one owned-process exit race on `eva-6ce1a0614ff5` / `cascade32`: the worker's `run_end` says complete, client usage is complete and the server is confirmed idle, but `killpg` raised `PermissionError` and the controller recorded no final child return code.

All **579 original artifacts** are retained through the [manifest](results/diagnostics-instrumentation-v1/arithmetic-s2/manifest.json), without rewriting source metadata or error records. The independent [proof/cost audit](results/diagnostics-instrumentation-v1/arithmetic-s2/proof-cost-audit.json) and [replay script](results/diagnostics-instrumentation-v1/arithmetic-s2/proof-cost-audit.py) verify 15,550 legal `Fraction` transitions, 326 illegal proposal flags, 303 original-task roots and successful reward ancestry. Request accounting matches **19,117 starts / 18,688 ends**, including 429 unfinished calls. Server-counter cost is independently known for all 192 cases. These consistency checks do not reinstate an invalid cohort. No accuracy table or arm ranking is produced; every original seed-2 case is rerun uniformly under the repaired instrumentation.

### Live instrumentation validation

The separate [idle-boundary grader verification receipt](results/instrumentation-verification-20261115.json) records three passing CPU-only smokes under the fixed source: a normal candidate, a timed-out candidate classified `candidate_timeout`, and a memory-exhaustion candidate with retained kernel `OOMKilled:true` / exit 137 classified `candidate_oom`. All reports have `infrastructure:false` and successful cleanup, with zero owned leftovers. This validates the repaired classification path prospectively; it does not supply a missing historical OOM flag to the original diagnostic runs. Replacement cohorts remain under the frozen model policies, datasets, prompts and budgets.

### Interrupted replacement arithmetic seed 2: serving failure

The subsequent fixed-instrumentation attempt, source `6c9dfe83bcb7fca46bc3059914b7407cabf865d4`, was interrupted by a **serving-engine failure**. It is excluded and preserved separately in [arithmetic-s2-serving-failure](results/diagnostics-instrumentation-v1/arithmetic-s2-serving-failure/), with [partial validity/usage details](results/diagnostics-instrumentation-v1/arithmetic-s2-serving-failure/diagnostic-validity.json) and an [export manifest](results/diagnostics-instrumentation-v1/arithmetic-s2-serving-failure/manifest.json). This cause is distinct from the earlier process-exit race and candidate-resource grader classification.

The main researcher's operational report identifies Spark02 CUDA illegal memory access, followed by HTTP 500 responses and resets; generation was halted and the owned controller was terminated with exit `-15`. Exported request traces independently retain **32 HTTP 500 errors and 220 connection resets**. The CUDA diagnosis and controller exit code are external operational evidence and are not inserted into the original raw metadata.

All **99 original files** are preserved. There are 192 planned cases, **28 recorded summary rows and 32 started traces**; four started traces lack a summary row, 164 planned cases have no summary, and 160 have no trace. The original metadata has no final completion time, completed count, final source hashes, unchanged-source verification, incomplete/missing-case/slot-failure markers or final batch wall. Those fields remain **absent** in the export, with the derived exclusion/partial status recorded only in the separate validity file.

Recorded request accounting contains **2823 starts / 2763 ends**, 60 unfinished requests, and 252 ended requests without reported prompt/completion usage. Observed client usage of **376,861 prompt / 92,397 completion tokens is a lower bound**. Server cost is explicitly known for 17 of the 28 summary rows; 11 rows and all four traces without a summary lack final known server cost. Known-case counter subtotals are preserved separately, and full-cohort server cost remains null. No missing response, usage or final metadata is replaced by zero or fabricated completion. No accuracy table, ranking or completed-cohort proof audit is produced for this partial attempt.
