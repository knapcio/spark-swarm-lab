| Method | Solved | Accuracy | 95% interval |
|---|---:|---:|---:|
| index_explicit | 17/24 | 70.8% | 54.2%–87.5% |
| index_original | 9/24 | 37.5% | 12.5%–66.7% |
| scribe_empty | 10/24 | 41.7% | 12.5%–70.8% |
| scribe_full | 20/24 | 83.3% | 66.7%–95.8% |
| scribe_tail | 15/24 | 62.5% | 45.8%–79.2% |
| value_explicit | 14/24 | 58.3% | 41.7%–75.0% |
| value_original | 8/24 | 33.3% | 8.3%–58.3% |

| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |
|---|---:|---:|---:|---:|---:|
| index_explicit | 24 | 122275 | 122275 | 24/24 | 40.343 / 70.979 |
| index_original | 24 | 159505 | 159505 | 24/24 | 70.110 / 73.164 |
| scribe_empty | 37 | 159325 | 159325 | 24/24 | 68.486 / 72.081 |
| scribe_full | 37 | 151285 | 151285 | 24/24 | 66.483 / 72.489 |
| scribe_tail | 38 | 164036 | 164036 | 24/24 | 68.234 / 73.244 |
| value_explicit | 24 | 146913 | 146913 | 24/24 | 64.843 / 71.902 |
| value_original | 24 | 164269 | 164269 | 24/24 | 70.898 / 75.045 |

* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.

Winner-biased development selection on 8 reused tasks x 3 seeds; not fresh generalization or fleet throughput
