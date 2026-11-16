**Scope warning:** all-zero task-cluster bootstrap intervals are empirical degeneracy, not a true zero success probability. This profile remains separate from other budgets; see [failure-mode notes](../REPORT.md).

| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Color-aligned consensus | 0/36 | 0.0% | 0.0%–0.0% |
| Evolution with crossover | 0/36 | 0.0% | 0.0%–0.0% |
| Mutation-only evolution | 0/36 | 0.0% | 0.0%–0.0% |
| Four repair chains | 0/36 | 0.0% | 0.0%–0.0% |
| Independent resampling | 0/36 | 0.0% | 0.0%–0.0% |
| Review-guided elites | 0/36 | 0.0% | 0.0%–0.0% |
| Sequential repair | 0/36 | 0.0% | 0.0%–0.0% |
| Weighted color consensus | 0/36 | 0.0% | 0.0%–0.0% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| Color-aligned consensus | 2304 | 384945 | 384945 | 36/36 | 37.805 / 122.578 |
| Evolution with crossover | 2304 | 375150 | 375150 | 36/36 | 39.618 / 125.058 |
| Mutation-only evolution | 2304 | 374530 | 374530 | 36/36 | 37.781 / 127.824 |
| Four repair chains | 2304 | 275364 | 275364 | 36/36 | 36.128 / 90.503 |
| Independent resampling | 2304 | 401219 | 401219 | 36/36 | 40.478 / 126.172 |
| Review-guided elites | 2304 | 308675 | 308675 | 36/36 | 74.577 / 122.343 |
| Sequential repair | 2304 | 269402 | 269402 | 36/36 | 74.712 / 151.905 |
| Weighted color consensus | 2304 | 379528 | 379528 | 36/36 | 38.061 / 126.308 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Separate CSP profile; complete provided cohorts only, task-cluster intervals retain all observed seeds. Budgets/thinking profiles never pooled; no mixed-queue per-arm throughput inference.
