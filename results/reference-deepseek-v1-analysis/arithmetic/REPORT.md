**Reference scope:** Native TP4 and single-replica Nemotron recipes are not equal compute/reasoning settings. All-pass empirical intervals can degenerate; see [resource and verification notes](../REPORT.md).

| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Native DeepSeek direct 8K | 72/72 | 100.0% | 100.0%–100.0% |
| Nemotron four full plans | 49/72 | 68.1% | 54.2%–80.6% |
| Nemotron sequential refinement | 45/72 | 62.5% | 47.2%–77.8% |
| Nemotron single full plan 8K | 18/72 | 25.0% | 15.3%–34.7% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| Native DeepSeek direct 8K | 72 | 79386 | None | 0/72 | 18.286 / 66.482 |
| Nemotron four full plans | 288 | 993520* | 1631105 | 72/72 | 94.361 / 131.402 |
| Nemotron sequential refinement | 150 | 837867* | 980664 | 72/72 | 120.324 / 182.083 |
| Nemotron single full plan 8K | 72 | 516134 | 516134 | 72/72 | 68.945 / 74.154 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Separate fixed-suite quality reference: custom abliterated DeepSeek517efa TP4/native effort75/defaulttop_p.95 vs single-replica Nemotron/variousrecipes. Not equal reasoning/compute, not causal headcount/model isolation; task-cluster intervals retain3seeds, pointwise paired contrasts do not assume identical sampling. Empirical all-pass intervals may collapse and do not imply general100% correctness. Native client usage/case wall only; global/server cost unknown, no fleet-throughput/billed-cost claim. Opus unavailable and GLM notrun are missing providers, never zero scores. Coding uses independently confirmed ORIGINAL holdout outcomes, never posthoc robustness substitution.
