**Scope warning:** all-zero task-cluster bootstrap intervals are empirical degeneracy, not a true zero success probability. This profile remains separate from other budgets; see [failure-mode notes](../REPORT.md).

| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| Color-aligned consensus | 0/36 | 0.0% | 0.0%–0.0% |
| Evolution with crossover | 0/36 | 0.0% | 0.0%–0.0% |
| Four repair chains | 0/36 | 0.0% | 0.0%–0.0% |
| Independent resampling | 0/36 | 0.0% | 0.0%–0.0% |
| Review-guided elites | 0/36 | 0.0% | 0.0%–0.0% |
| Sequential repair | 0/36 | 0.0% | 0.0%–0.0% |
| Weighted color consensus | 0/36 | 0.0% | 0.0%–0.0% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| Color-aligned consensus | 576 | 97895 | 97895 | 36/36 | 10.067 / 32.090 |
| Evolution with crossover | 576 | 94897 | 94897 | 36/36 | 10.379 / 31.731 |
| Four repair chains | 576 | 75815 | 75815 | 36/36 | 9.433 / 27.960 |
| Independent resampling | 576 | 103101 | 103101 | 36/36 | 11.114 / 33.287 |
| Review-guided elites | 576 | 80038 | 80038 | 36/36 | 16.859 / 29.721 |
| Sequential repair | 576 | 68163 | 68163 | 36/36 | 18.914 / 41.533 |
| Weighted color consensus | 576 | 96900 | 96900 | 36/36 | 9.374 / 31.811 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Separate CSP profile; complete provided cohorts only, task-cluster intervals retain all observed seeds. Budgets/thinking profiles never pooled; no mixed-queue per-arm throughput inference.
