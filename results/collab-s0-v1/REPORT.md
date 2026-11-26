# collab-s0-v1 (s0)

Decision: **STOP**

| check | value | limit | met | on fail |
|---|---:|---|---|---|
| prefix_identical | 1.0 | == 1.0 | True | fix |
| turn_boundaries | 1.0 | == 1.0 | True | fix |
| cached_share | 0.9297896880905053 | >= 0.95 | False | fix or fallback B |
| checkpoint_latency | 14.509669661521912 | <= 5.0 s | False | fix or fallback B |
| reply_parse | 1.0 | >= 0.90 | True | fix the note prompt once, then fallback B |
| note_within_256 | 0.45 | >= 0.90 | False | fix the note prompt once, then fallback B |
| arith_results_correct | 0.8125 | >= 0.90 | False | stop |
| focus_distinct | 0.9927007299270073 | >= 0.75 | True | stop: nothing to divide |
| answer_at_once | 0.0 | <= 0.20 | True | stop, or fallback B |
| own_repeat | -0.040679494762130355 | <= +0.10 | True | stop, or fallback B |

Proxies: checkpoint_latency (sum of two first-token times), own_repeat (recorded texts split by character share)
By family: {"arith": {"checkpoints": 80, "singleton_groups": 0, "reply_kinds": {"note": 80}, "note_tokens_median": 272.5}, "coding": {"checkpoints": 20, "singleton_groups": 5, "reply_kinds": {"note": 20}, "note_tokens_median": 224.5}}
