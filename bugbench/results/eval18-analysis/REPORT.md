# bugbench evaluation: 18 new cases x 2 seeds

Six original multi-module projects (900-1,500 lines, larger than one 16K context), three planted bugs each (easy/medium/hard), frozen before any model call. Agents see the buggy project and a user bug report, never the hidden probes. Selection is arbiter-free (public tests, agent-written tests, votes, model reviews); the selected patch receives exactly one hidden grade. "Oracle" = some candidate patch would have passed (hindsight upper bound, never used for selection).

| Policy | Fixed (hidden grade) | Oracle any | No patch | Mean calls | Mean completion tokens |
|---|---:|---:|---:|---:|---:|
| S1 — single navigator | **18/36** (50%) | 18 | 13 | 4.8 | 15,888 |
| S3 — 8 independent navigators + vote | **26/36** (72%) | 26 | 5 | 36.6 | 116,996 |
| T3 — 8 test-first agents + cross-validation by peers’ tests | **26/36** (72%) | 27 | 4 | 59.0 | 210,592 |
| V3 — 8 independent navigators + model reviewer | **28/36** (78%) | 29 | 4 | 38.3 | 122,233 |

Paired differences vs S1 (case-cluster bootstrap 95% interval):
- S3 − S1: +8% to +39%
- T3 − S1: +6% to +42%
- V3 − S1: +14% to +44%

| Case | S1 | S3 | T3 | V3 |
|---|---:|---:|---:|---:|
| junction-b1-exact-transfer-time | ·✓ | ✓✓ | ✓✓ | ✓✓ |
| junction-b2-walk-time-rounding | ✓✓ | ✓✓ | ·✓ | ✓✓ |
| junction-b3-night-listing-stale | ·· | ·· | ·· | ·· |
| patchwork-b1-hunk-merge-gap | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| patchwork-b2-context-newline-marker | ·· | ·· | ·· | ✓· |
| patchwork-b3-fuzz-trims-patch | ·· | ·· | ·· | ·· |
| quarry-b1-desc-tie-order | ·✓ | ✓✓ | ✓✓ | ✓✓ |
| quarry-b2-right-assoc-minus | ·· | ·· | ✓· | ✓✓ |
| quarry-b3-failed-insert-keys | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| relay-b1-wait-rounds-down | ·✓ | ✓✓ | ✓✓ | ✓✓ |
| relay-b2-ready-time-tiebreak | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| relay-b3-rejected-batch-tokens | ·· | ✓✓ | ✓✓ | ·✓ |
| tally-b1-discount-last-day | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| tally-b2-vat-per-line | ·· | ✓✓ | ✓✓ | ✓✓ |
| tally-b3-rejected-discount-payment | ·· | ·· | ·· | ·· |
| trellis-b1-caret-zero-patch | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| trellis-b2-install-order-ready | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| trellis-b3-backtrack-leak | ✓· | ✓✓ | ✓✓ | ✓✓ |

Infrastructure faults (excluded, rerun in the continuation): 2 [('eval18-v1', 'trellis-b1-caret-zero-patch__T3__s1'), ('eval18-v1', 'trellis-b2-install-order-ready__T3__s1')]. Two runs are pooled per the frozen plan amendment; attempts are independent.
