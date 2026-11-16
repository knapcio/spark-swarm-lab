# Completed direct-assignment CSP profiles

Three separately declared profiles on the same 12 planted graph-coloring evaluation tasks produced no verified solutions. The profiles remain separate: the core and extended OFF studies use three replication seeds; the late ON study uses one. The original automatic thinking-ON stage remains recorded as time-skipped. Its later manually admitted execution is a separate late exploratory cohort.

| Profile | Evaluation cases | Solved | Model calls | Actual server input tokens | Actual server output tokens | Known server cost cases |
|---|---:|---:|---:|---:|---:|---:|
| Core OFF, 16 calls | 252 | 0/252 | 4,032 | 6,107,124 | 616,809 | 252/252 |
| Extended OFF, 64 calls | 288 | 0/288 | 18,432 | 29,011,473 | 2,768,813 | 288/288 |
| Late ON, 16 calls | 96 | 0/96 | 1,536 | 2,148,566 | 6,093,601 | 96/96 |

## Failure modes and interpretation

**Late ON:** all 1,464 assignment-producing responses finish with `length`, contain nonempty separate reasoning, and have no answer content. The other 72 calls are reviewer responses and finish with content. The 4,096-completion-token per-call budget includes reasoning. These 0/96 outcomes therefore measure answer/format exhaustion under this particular ON budget and prompt/serving recipe; they do not prove that the model cannot color these graphs. There are no observed infrastructure faults, controlled deadlines, unfinished calls or unknown server costs in this completed cohort. The exact server/client totals agree: 2,148,566 input and 6,093,601 completion tokens. Whole mixed-cohort fleet wall is 7,268.164 seconds; it is not per-arm throughput.

**OFF:** independent audits identify malformed assignment cardinality/domain as prominent failure modes. These differ from the ON reasoning-without-final-answer failure. The OFF profiles use 512-token calls: core limits16 calls/8,192 completion tokens per case with180-second nominal deadline; extended limits64 calls/32,768 completion tokens with600-second deadline. The ON profile allows16 calls/65,536 completion tokens with900-second deadline. HTTP request timeouts exceed those case budgets by30seconds. Identical graphs do not make these different budget/recipe profiles a controlled reasoning-only comparison.

**Uncertainty:** each profile uses 5,000 task-cluster bootstrap replicates (seed20261115), retaining all observed repetition seeds within each of the 12 graph clusters. Every empirical task outcome is zero, so the bootstrap intervals collapse to [0,0]. Those degenerate empirical intervals are not proof of a true zero success probability, nor evidence that all methods are equally capable on other graphs or budgets. Repeated seeds do not create additional independent graph tasks.

## Profiles and artifacts

### Core OFF, 16 calls

7 arms, 12 distinct graphs, seeds 1, 2, 3: 252 complete cases. No budgets or source variants are pooled across profiles.

| Method | Solved | Actual calls | Client output tokens | Server cost coverage |
|---|---:|---:|---:|---:|
| democracy4 | 0/36 | 576 | 97,895 | 36/36 |
| evolution4 | 0/36 | 576 | 94,897 | 36/36 |
| parallel_repair4 | 0/36 | 576 | 75,815 | 36/36 |
| resample | 0/36 | 576 | 103,101 | 36/36 |
| review_elites4 | 0/36 | 576 | 80,038 | 36/36 |
| sequential | 0/36 | 576 | 68,163 | 36/36 |
| weighted_democracy4 | 0/36 | 576 | 96,900 | 36/36 |

[JSON](core_off16/analysis.json), [CSV](core_off16/summary.csv), [paired cases](core_off16/paired-cases.csv), [accuracy PNG](core_off16/accuracy-cluster95.png), [SVG](core_off16/accuracy-cluster95.svg), [completion-cost PNG](core_off16/success-vs-client-output-cost.png)

### Extended OFF, 64 calls

8 arms, 12 distinct graphs, seeds 1, 2, 3: 288 complete cases. No budgets or source variants are pooled across profiles.

| Method | Solved | Actual calls | Client output tokens | Server cost coverage |
|---|---:|---:|---:|---:|
| democracy4 | 0/36 | 2,304 | 384,945 | 36/36 |
| evolution4 | 0/36 | 2,304 | 375,150 | 36/36 |
| evolution_mutation4 | 0/36 | 2,304 | 374,530 | 36/36 |
| parallel_repair4 | 0/36 | 2,304 | 275,364 | 36/36 |
| resample | 0/36 | 2,304 | 401,219 | 36/36 |
| review_elites4 | 0/36 | 2,304 | 308,675 | 36/36 |
| sequential | 0/36 | 2,304 | 269,402 | 36/36 |
| weighted_democracy4 | 0/36 | 2,304 | 379,528 | 36/36 |

[JSON](extended_off64/analysis.json), [CSV](extended_off64/summary.csv), [paired cases](extended_off64/paired-cases.csv), [accuracy PNG](extended_off64/accuracy-cluster95.png), [SVG](extended_off64/accuracy-cluster95.svg), [completion-cost PNG](extended_off64/success-vs-client-output-cost.png)

### Late ON, 16 calls

8 arms, 12 distinct graphs, seeds 1: 96 complete cases. No budgets or source variants are pooled across profiles.

| Method | Solved | Actual calls | Client output tokens | Server cost coverage |
|---|---:|---:|---:|---:|
| democracy4 | 0/12 | 192 | 786,432 | 12/12 |
| evolution4 | 0/12 | 192 | 786,432 | 12/12 |
| evolution_mutation4 | 0/12 | 192 | 786,432 | 12/12 |
| parallel_repair4 | 0/12 | 192 | 786,432 | 12/12 |
| resample | 0/12 | 192 | 786,432 | 12/12 |
| review_elites4 | 0/12 | 192 | 588,577 | 12/12 |
| sequential | 0/12 | 192 | 786,432 | 12/12 |
| weighted_democracy4 | 0/12 | 192 | 786,432 | 12/12 |

[JSON](thinking_on16/analysis.json), [CSV](thinking_on16/summary.csv), [paired cases](thinking_on16/paired-cases.csv), [accuracy PNG](thinking_on16/accuracy-cluster95.png), [SVG](thinking_on16/accuracy-cluster95.svg), [completion-cost PNG](thinking_on16/success-vs-client-output-cost.png)

## Context and provenance

Separate zero-model CPU references on the original evaluation graphs solve30/36 with min-conflicts,18/36 with the genetic search, and0/36 with random assignments. They use different primitive evaluation budgets (and different algorithms), so a CPU fitness evaluation is not a model call, and these counts do not establish a matched-budget efficiency comparison. See the [completed CPU-reference audit](../csp-independent-audit-20261116/FINAL_AUDIT.json). The separately trained reusable programs and their fresh-graph checks are also a different representation/execution regime; they are not pooled into this direct-assignment study.

All seven completed evaluation cohorts use frozen source dadba8c29cd5b11bd71e49b4c8ba4e6ee5adaab5 and pinned runtime072b628126f36aa559fa864372118c7e0497e44d1b37d29be99ea3c7f8cf6ec5. The reporting helper replays exact candidate payload verification and candidate/review/consensus ancestry, reconciles request IDs/usage and known idle-delimited server counters, and verifies full arm/task/seed coverage. Original model outputs and raw evidence remain unchanged. Client/server input and output tokens are separate measurements, not equal GPU-cost units. No per-arm fleet rate is inferred from mixed-arm queue wall times.

The lineage exports in this report describe these CSP assignment/review/consensus events. They must not be used to label the newer reviewer-program traces as a complete DAG: those require their own typed reviewer, target and repair-guidance adapter. Unselected candidates are not automatically mathematically wrong; reviewers remain unverified model suggestions.

[Lineage index](lineage-index.json), [input/source/output manifest](manifest.json), [report QA](report-qa.json), [exact prepared command](report-plan.json). The independently completed late-ON audit is recorded by SHA in the manifest.
