# collab-s0-v2 (s0)

Decision: **FIX**

| check | value | limit | met | on fail |
|---|---:|---|---|---|
| prefix_identical | 1.0 | == 1.0 | True | fix |
| turn_boundaries | 1.0 | == 1.0 | True | fix |
| cached_share | 0.9659931650183398 | >= 0.95 | True | fix or fallback B |
| checkpoint_latency | 23.492505431175232 | <= 5.0 s | False | fix or fallback B |
| reply_parse | 1.0 | >= 0.90 | True | fix the note prompt once, then fallback B |
| note_within_256 | 1.0 | >= 0.90 | True | fix the note prompt once, then fallback B |
| arith_results_correct | 1.0 | >= 0.90 | True | stop |
| arith_coverage | 0.9 | >= 0.75 | True | fix the note prompt once, then fallback B |
| focus_distinct | 0.948905109489051 | >= 0.75 | True | stop: nothing to divide |
| answer_at_once | 0.0 | <= 0.20 | True | stop, or fallback B |
| own_repeat | -0.03508061410683866 | <= +0.10 | True | stop, or fallback B |

Proxies: checkpoint_latency (sum of two first-token times), own_repeat (recorded texts split by character share)
By family: {"arith": {"checkpoints": 80, "singleton_groups": 0, "reply_kinds": {"note": 80}, "note_tokens_median": 119.0}, "coding": {"checkpoints": 20, "singleton_groups": 5, "reply_kinds": {"note": 20}, "note_tokens_median": 120.5}}
Statements: {"claims_made": 300, "claims_dropped": 162, "drop_rate": 0.54, "claims_unverified": 20, "claims_agent_checked": 47, "claims_verified": 71, "drops_by_reason": {"malformed tried (approach: ...; observed: ...)": 79, "malformed checked (input: ...; expected: ...; got: ...)": 75, "false equation": 5, "checker call": 2, "known case; the observation goes to the checker call": 1}, "checker_no_verdict": 0, "prefilter_evaluable": 140, "prefilter_accuracy": 0.9642857142857143, "schema_violations": {}, "by_family": {"arith": {"claims_made": 240, "claims_dropped": 123, "drop_rate": 0.5125, "claims_unverified": 6, "claims_agent_checked": 40, "claims_verified": 71, "drops_by_reason": {"malformed tried (approach: ...; observed: ...)": 59, "malformed checked (input: ...; expected: ...; got: ...)": 59, "false equation": 4, "checker call": 1}, "checker_no_verdict": 0, "prefilter_evaluable": 139, "prefilter_accuracy": 0.9712230215827338, "schema_violations": {}}, "coding": {"claims_made": 60, "claims_dropped": 39, "drop_rate": 0.65, "claims_unverified": 14, "claims_agent_checked": 7, "claims_verified": 0, "drops_by_reason": {"malformed tried (approach: ...; observed: ...)": 20, "malformed checked (input: ...; expected: ...; got: ...)": 16, "checker call": 1, "false equation": 1, "known case; the observation goes to the checker call": 1}, "checker_no_verdict": 0, "prefilter_evaluable": 1, "prefilter_accuracy": 0.0, "schema_violations": {}}}, "verifier_calls": 50, "verifier_prompt_tokens": 706522, "verifier_new_prompt_tokens": 6229, "verifier_completion_tokens": 304, "verifier_cancelled": 0, "verifier_latency_median_s": 0.7508801221847534, "verifier_latency_p90_s": 0.9723200798034668}
Arithmetic statements: 117 made, 80 evaluable, 0 false, 8 not parseable
Board-phase prefill by node: {"http://127.0.0.1:18081/v1": {"prompt_tokens": 321834.0, "prefill_compute_tokens": 10666.0, "structural_new_tokens": 7249, "eviction_tokens": 3417.0, "best_possible_share": 0.9774759658706041}, "http://127.0.0.1:18082/v1": {"prompt_tokens": 312218.0, "prefill_compute_tokens": 9882.0, "structural_new_tokens": 6995, "eviction_tokens": 2887.0, "best_possible_share": 0.9775957824340685}, "http://127.0.0.1:18083/v1": {"prompt_tokens": 303439.0, "prefill_compute_tokens": 10319.0, "structural_new_tokens": 7180, "eviction_tokens": 3139.0, "best_possible_share": 0.9763379130566605}, "http://127.0.0.1:18084/v1": {"prompt_tokens": 312271.0, "prefill_compute_tokens": 9679.0, "structural_new_tokens": 7229, "eviction_tokens": 2450.0, "best_possible_share": 0.9768502358528329}}
