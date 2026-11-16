**Reference scope:** Native TP4 and single-replica Nemotron recipes are not equal compute/reasoning settings. All-pass empirical intervals can degenerate; see [resource and verification notes](../REPORT.md).

| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Native DeepSeek direct 8K | 54/54 | 100.0% | 100.0%–100.0% |
| Nemotron direct thinking | 53/54 | 98.1% | 94.4%–100.0% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| Native DeepSeek direct 8K | 54 | 43968 | None | 0/54 | 16.751 / 50.444 |
| Nemotron direct thinking | 54 | 155364 | 155364 | 54/54 | 23.759 / 61.884 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Separate fixed-suite quality reference: custom abliterated DeepSeek517efa TP4/native effort75/defaulttop_p.95 vs single-replica Nemotron/variousrecipes. Not equal reasoning/compute, not causal headcount/model isolation; task-cluster intervals retain3seeds, pointwise paired contrasts do not assume identical sampling. Empirical all-pass intervals may collapse and do not imply general100% correctness. Native client usage/case wall only; global/server cost unknown, no fleet-throughput/billed-cost claim. Opus unavailable and GLM notrun are missing providers, never zero scores. Coding uses independently confirmed ORIGINAL holdout outcomes, never posthoc robustness substitution.
