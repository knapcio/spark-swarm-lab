**Scope warning:** all-zero task-cluster bootstrap intervals are empirical degeneracy, not a true zero success probability. This profile remains separate from other budgets; see [failure-mode notes](../REPORT.md).

| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Color-aligned consensus | 0/12 | 0.0% | 0.0%–0.0% |
| Evolution with crossover | 0/12 | 0.0% | 0.0%–0.0% |
| Mutation-only evolution | 0/12 | 0.0% | 0.0%–0.0% |
| Four repair chains | 0/12 | 0.0% | 0.0%–0.0% |
| Independent resampling | 0/12 | 0.0% | 0.0%–0.0% |
| Review-guided elites | 0/12 | 0.0% | 0.0%–0.0% |
| Sequential repair | 0/12 | 0.0% | 0.0%–0.0% |
| Weighted color consensus | 0/12 | 0.0% | 0.0%–0.0% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| Color-aligned consensus | 192 | 786432 | 786432 | 12/12 | 249.641 / 285.807 |
| Evolution with crossover | 192 | 786432 | 786432 | 12/12 | 248.568 / 282.389 |
| Mutation-only evolution | 192 | 786432 | 786432 | 12/12 | 251.908 / 286.445 |
| Four repair chains | 192 | 786432 | 786432 | 12/12 | 244.666 / 286.858 |
| Independent resampling | 192 | 786432 | 786432 | 12/12 | 256.091 / 283.738 |
| Review-guided elites | 192 | 588577 | 588577 | 12/12 | 247.691 / 277.862 |
| Sequential repair | 192 | 786432 | 786432 | 12/12 | 533.959 / 604.683 |
| Weighted color consensus | 192 | 786432 | 786432 | 12/12 | 250.002 / 288.133 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Separate CSP profile; complete provided cohorts only, task-cluster intervals retain all observed seeds. Budgets/thinking profiles never pooled; no mixed-queue per-arm throughput inference.
