# Native DeepSeek quality reference

The completed native DeepSeek reference solves 72/72 arithmetic attempts and 54/54 coding attempts on the same frozen suites. Results are a separate model/runtime reference, not a matched-compute swarm comparison or an isolated test of agent count. Opus is unavailable and GLM was not run; neither receives a zero score.

## Fixed-suite quality

| Domain | Method | Solved | Accuracy | Task-cluster empirical 95% interval |
|---|---|---:|---:|---:|
| arithmetic | Native DeepSeek direct 8K | 72/72 | 100.00% | 100.00–100.00% |
| arithmetic | Nemotron four full plans | 49/72 | 68.06% | 54.17–80.56% |
| arithmetic | Nemotron sequential refinement | 45/72 | 62.50% | 47.22–77.78% |
| arithmetic | Nemotron single full plan 8K | 18/72 | 25.00% | 15.28–34.72% |
| coding | Native DeepSeek direct 8K | 54/54 | 100.00% | 100.00–100.00% |
| coding | Nemotron direct thinking | 53/54 | 98.15% | 94.44–100.00% |

The bootstrap uses 5,000 replicates with fixed seed 20261115, resampling 24 arithmetic task clusters or 18 coding task clusters and retaining all three repetition seeds within each task. The 72/54 attempts are not 72/54 independent problems. Native all-pass empirical intervals collapse to 100%–100%; this is a finite-suite ceiling, not a guarantee of true 100% correctness or performance on other tasks.

## Paired descriptive contrasts

| Domain | Contrast, first minus second | Difference, percentage points | Pointwise task-cluster 95% interval |
|---|---|---:|---:|
| arithmetic | Native DeepSeek direct 8K − Nemotron four full plans | +31.94 | +19.44 to +45.83 |
| arithmetic | Native DeepSeek direct 8K − Nemotron sequential refinement | +37.50 | +22.22 to +52.78 |
| arithmetic | Native DeepSeek direct 8K − Nemotron single full plan 8K | +75.00 | +65.28 to +84.72 |
| coding | Native DeepSeek direct 8K − Nemotron direct thinking | +1.85 | +0.00 to +5.56 |

Pairs share task and repetition labels. Shared labels do not imply identical stochastic trajectories, equal reasoning settings, or common random numbers. Intervals are pointwise and unadjusted for multiple comparisons. The coding contrast is 1/54 attempts (1.85 percentage points), with an interval spanning 0; the finite suite is near its ceiling.

## Resources, budgets and measured cost

DeepSeek is the custom abliterated `mrfakename/DeepSeek-V4.1-Flash-1017-abliterated` checkpoint at revision 517efab9ccfef7f714dbd7d679f181a86f43ccf9. The configured response alias is `deepseek-v4.1-flash`, verified in every actual response and corroborated by the separately admitted runtime. It uses the native pico/dsgb10 engine and Rust frontend across four Sparks in TP4, effort 75 and default top_p 0.95. Nemotron uses the pinned Lightning30B-A3B NVFP4/vLLM0.32/DSpark3 recipe, with a task assigned to one independent Spark replica. All four replicas serve the Nemotron queue, while the native TP4 model shares its four-node model across reference cases. These resource allocations and reasoning controls differ. Full checkpoint-weight hashing and a complete native source-to-binary build identity remain unverified, as disclosed in the runtime receipt.

Native direct calls use a cap of 8,192 completion tokens and a whole-case budget of 180 seconds. Nemotron full-plan recipes use 8K calls, while four-plan ensembles or own-feedback refinement can make multiple calls and consume different actual work. The method, checkpoint, tokenizer, serving stack, stopping policy, reasoning implementation, and case scheduling are bundled differences; no isolated causal model/headcount or GPU-efficiency claim follows.

| Native domain | Actual client input | Actual client completion | Median / p95 occupied case wall, s | Known global/server cost |
|---|---:|---:|---:|---|
| arithmetic | 12,528 | 79,386 | 18.29 / 66.48 | unknown for all72 cases |
| coding | 14,109 | 43,968 | 16.75 / 50.44 | unknown for all54 cases |

The 126 Native calls report 26,637 client input and 123,354 completion tokens, including 115,243 reasoning tokens (already contained in the completion total, not added again). There are no controlled deadlines, unfinished calls, or missing client usage in this completed run. Native global/server token cost remains unknown for all 126 cases. Nemotron canceled-response client totals are lower bounds where marked in the detailed CSV/plots; its known server counters are a different measurement scope. Client token counts from different tokenizers are not equal GPU-cost or billed-cost units.

Whole Native 126-case batch wall is 798.315 seconds, including shared-endpoint scheduling, transport and coding grading. Occupied case wall includes controller and verification overhead. No per-arm fleet throughput, per-stream decode speed, global token rate, or price comparison is inferred from this mixed-domain reference batch.

## Verifier and provenance checks

All 126 unique frozen task/seed cases passed the complete-cohort/source gate and final independent audit before these statistics ran. Native metadata has no `verified` field: admission uses completed_cases=126, incomplete=false, errors=[], unchanged captured/final source and adapter identities, and the independent audit PASS. The five adapter files match Git revision630701211036c4e1f8b369cfc3b36d39ce181732; arithmetic/coding orchestration remains frozen at CBC revision cbcde299716b7842536b008880a089590e9816f8. Each attempt has one dispatched call; request seed/body, response model alias, answer/reasoning/usage fields, process completion and deadline semantics were checked.

Arithmetic replays 193 exact Fraction transitions and verifies every successful reward against the legal ancestry rooted in its original numbers. Coding checks 108 outer-parent feedback/holdout reports, c432 grader/image qualification, source/test payload hashes, frozen candidate selection before a single holdout, no holdout-driven retry, and successful cleanup. Candidate code was not executed during this offline report. Raw child observations are not retained, so this is not a claim of independently rerunning Python or reconstructing every coding output from observation logs.

Nemotron coding numbers use the original frozen holdout outcomes, which match independent outer-parent confirmation of those same partitions. Later posthoc robustness scores are separate and are not substituted here. Passing this finite holdout is not proof of correctness for every possible input. Original source, outputs and scores remain unchanged.

- [Arithmetic JSON](arithmetic/analysis.json), [CSV](arithmetic/summary.csv), [paired rows](arithmetic/paired-cases.csv), [contrasts](arithmetic/paired-deltas.csv), [PNG](arithmetic/accuracy-cluster95.png), [SVG](arithmetic/accuracy-cluster95.svg)
- [Coding JSON](coding/analysis.json), [CSV](coding/summary.csv), [paired rows](coding/paired-cases.csv), [contrasts](coding/paired-deltas.csv), [PNG](coding/accuracy-cluster95.png), [SVG](coding/accuracy-cluster95.svg)
- [Independent audit copy](evidence/independent-audit.json), [runtime admission](evidence/DEEPSEEK_REFERENCE_RUNTIME_ADMITTED.json), [frozen adapter receipt](evidence/DEEPSEEK_REFERENCE_EVALUATION_FROZEN.json), [raw metadata](evidence/metadata.json), [manifest](manifest.json)
