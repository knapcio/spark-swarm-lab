# Depth vs breadth on hard development tasks

Exploratory, arithmetic-hard-v1 development split (16 tasks x 3 seeds = 48 cases), 8 independent agents per case. Expected solved cases averaged over all agent subsets.

| Agent | Single-agent success | Mean completion tokens |
|---|---:|---:|
| forced_explicit | 41/192 (21.4%) | 6889 |
| long_forced_original | 43/96 (44.8%) | 12148 |
| long_forced_explicit | 34/96 (35.4%) | 12824 |

| Ceiling | Deep (long_forced_original) | Deep (long_forced_explicit) | Short (forced_explicit) |
|---|---:|---:|---:|
| 16K, all | 21.5 | 17.0 | 15.0 (2 agents) |
| 32K, all | 27.0 | 23.0 | 20.0 (4 agents) |
| 16K, 4-number | 14.0 | 11.0 | 9.2 (2 agents) |
| 32K, 4-number | 16.0 | 14.0 | 12.0 (4 agents) |
| 16K, 6-number | 7.5 | 6.0 | 5.8 (2 agents) |
| 32K, 6-number | 11.0 | 9.0 | 8.0 (4 agents) |

Errors [], wall 2515 s, 0 deadlines. Ceilings compare budgets; deep agents actually used ~1.7x the tokens of short agents on average.
