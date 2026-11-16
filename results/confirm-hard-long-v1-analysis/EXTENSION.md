# 8 deep agents on hard evaluation tasks

Pooled confirm-hard-long-v1 (agents 0-3) and confirm-hard-long-ext-v1 (agents 4-7): same agent type (long_forced_original) and source ce6c0b6, different seeds, no wall-clock limits.

| Deep agents k | Expected solved / 144 |
|---:|---:|
| 1 | 52.8 |
| 2 | 75.6 |
| 3 | 88.4 |
| 4 | 96.4 |
| 5 | 101.8 |
| 6 | 105.7 |
| 7 | 108.6 |
| 8 | 111.0 |

All 8: **111/144**. DeepSeek with an 8K cap: 98.5 single call, 107 with two calls (81/288 of its hard calls were truncated); the 32K-cap DeepSeek measurement is pending.

Run note: all 576 extension traces end with run_end (0 infrastructure failures). The controller recorded 575 summary rows; one controller thread hung after its worker had exited (22:15) and never recorded eva-h4a519b4f65d s1 a2. That row is reconstructed from its complete trace; the hung controller (no child processes) was stopped at 00:15 before writing final metadata. A macOS `sample` of the hung process is kept locally.
