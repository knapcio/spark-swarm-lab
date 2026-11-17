# Deep coding agents on coding-hard-v1 evaluation (24 tasks x 3 seeds)

Selection by feedback tests only; the selected program is scored once on holdout tests (CPU sandbox). Same tasks/seeds as coding-hard-eval-v1.

| Agents | Original single call (8K) | Budget-forced (8K) | **Deep (16K)** |
|---:|---:|---:|---:|
| 1 | 4 | 22 | 22 |
| 2 | 6 | 22 | 30 |
| 3 | 9 | 24 | 32 |
| 4 | 9 | 24 | 34 |
| 5 | — | 26 | — |
| 6 | — | 27 | — |
| 7 | — | 27 | — |
| 8 | — | 28 | — |

Per agent: deep 100/288 holdout-correct proposals (198 parsed); budget-forced 140/576. Mean completion tokens per agent: deep 14315, budget-forced 7949.

Four deep agents (16K each, 64K ceiling) solve 34/72 vs 28/72 for eight 8K agents (65.5K ceiling). Errors []; run concurrent with the bugbench evaluation (no wall-clock limits).
