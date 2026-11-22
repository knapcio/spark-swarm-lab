# One DeepSeek on arithmetic-hard-v9 and the pooled B+ vs DeepSeek test (deepseek-hard9-v1)

Plan [`DEEPSEEK_HARD9_PLAN.json`](../../DEEPSEEK_HARD9_PLAN.json) (f266225) is the hard-v5/v6/v7 DeepSeek plan on the
fresh hard-v9 tasks, frozen before any DeepSeek call on them and before any hard-v9 swarm result was read; it
pre-registers the pooled hard-v7 + hard-v9 test of the default swarm B+ against One DeepSeek. Errors: [].

| Set | Cases | Inkling swarm | Wrong | One DeepSeek | Swarm vs DeepSeek (paired) | Hybrid |
|---|---:|---:|---:|---:|---|---|
| hard-v9, B+ roll8cancel | 96 | **86** | 0 | 77 | +12 / -3 (p = 0.035) | 89 (10 DS calls) |
| hard-v9, roll8repair | 96 | **83** | 0 | 77 | +10 / -4 (p = 0.18) | 87 (13 DS calls) |
| **Pooled hard-v7 + v9, B+ (pre-registered)** | 192 | **176** | 0 | 156 | +25 / -5 (p = 0.00032) | 181 (16 DS calls) |

**Pooled (pre-registered): B+ 176 vs One DeepSeek 156 over 192 cases, paired +25 / -5
(p = 0.00032), 0 wrong answers for the swarm.**

Cost on hard-v9 (same four Sparks): One DeepSeek 136.66 Wh, 1.77 Wh per solved case, 67 min,
8,123 completion tokens per case; B+ 167.9 Wh, 1.95 Wh per solved case,
88 min, 69,107 server tokens per case.

Numbers: [deepseek.json](deepseek.json); report script `inkling/report_ds_hard9.py`.
