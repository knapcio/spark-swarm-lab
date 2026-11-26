# collab-s0-v3 (s0)

Decision: **PASS**

| check | value | limit | met | on fail |
|---|---:|---|---|---|
| prefix_identical | 1.0 | == 1.0 | True | fix |
| turn_boundaries | 1.0 | == 1.0 | True | fix |
| cached_share | 0.9673535569402424 | >= 0.95 | True | fix or fallback B |
| checkpoint_latency | 3.1446374654769897 | <= 5.0 s | True | fix or fallback B |
| reply_parse | 1.0 | >= 0.90 | True | fix the note prompt once, then fallback B |
| note_within_256 | 1.0 | >= 0.90 | True | fix the note prompt once, then fallback B |
| arith_results_correct | 1.0 | >= 0.90 | True | stop |
| arith_coverage | 0.95 | >= 0.75 | True | fix the note prompt once, then fallback B |
| focus_distinct | 0.9781021897810219 | >= 0.75 | True | stop: nothing to divide |
| answer_at_once | 0.0 | <= 0.20 | True | stop, or fallback B |
| own_repeat | -0.03130325917656797 | <= +0.10 | True | stop, or fallback B |

Proxies: checkpoint_latency (sum of two first-token times), own_repeat (recorded texts split by character share)
By family: {"arith": {"checkpoints": 80, "singleton_groups": 0, "reply_kinds": {"note": 80}, "note_tokens_median": 113.0}, "coding": {"checkpoints": 20, "singleton_groups": 5, "reply_kinds": {"note": 20}, "note_tokens_median": 116.0}}
Statements: {"claims_made": 300, "claims_dropped": 144, "drop_rate": 0.48, "claims_unverified": 19, "claims_agent_checked": 61, "claims_verified": 76, "drops_by_reason": {"malformed tried (approach: ...; observed: ...)": 68, "malformed checked (input: ...; expected: ...; got: ...)": 69, "false equation": 4, "checker call": 2, "known case; the observation goes to the checker call": 1}, "checker_no_verdict": 0, "prefilter_evaluable": 136, "prefilter_accuracy": 0.9705882352941176, "schema_violations": {}, "by_family": {"arith": {"claims_made": 240, "claims_dropped": 105, "drop_rate": 0.4375, "claims_unverified": 3, "claims_agent_checked": 56, "claims_verified": 76, "drops_by_reason": {"malformed tried (approach: ...; observed: ...)": 49, "malformed checked (input: ...; expected: ...; got: ...)": 51, "false equation": 3, "checker call": 2}, "checker_no_verdict": 0, "prefilter_evaluable": 135, "prefilter_accuracy": 0.9777777777777777, "schema_violations": {}}, "coding": {"claims_made": 60, "claims_dropped": 39, "drop_rate": 0.65, "claims_unverified": 16, "claims_agent_checked": 5, "claims_verified": 0, "drops_by_reason": {"malformed tried (approach: ...; observed: ...)": 19, "malformed checked (input: ...; expected: ...; got: ...)": 18, "false equation": 1, "known case; the observation goes to the checker call": 1}, "checker_no_verdict": 0, "prefilter_evaluable": 1, "prefilter_accuracy": 0.0, "schema_violations": {}}}, "verifier_calls": 64, "verifier_prompt_tokens": 871027, "verifier_new_prompt_tokens": 7767, "verifier_completion_tokens": 391, "verifier_cancelled": 0, "verifier_latency_median_s": 0.7225364446640015, "verifier_latency_p90_s": 0.9319279193878174}
Arithmetic statements: 135 made, 89 evaluable, 0 false, 4 not parseable
Board-phase prefill by node: {"http://127.0.0.1:18081/v1": {"prompt_tokens": 321934.0, "prefill_compute_tokens": 10510.0, "structural_new_tokens": 7410, "eviction_tokens": 3100.0, "best_possible_share": 0.976982859840837}, "http://127.0.0.1:18082/v1": {"prompt_tokens": 312327.0, "prefill_compute_tokens": 9863.0, "structural_new_tokens": 7239, "eviction_tokens": 2624.0, "best_possible_share": 0.9768223688634028}, "http://127.0.0.1:18083/v1": {"prompt_tokens": 303378.0, "prefill_compute_tokens": 9746.0, "structural_new_tokens": 7332, "eviction_tokens": 2414.0, "best_possible_share": 0.9758321302137927}, "http://127.0.0.1:18084/v1": {"prompt_tokens": 312339.0, "prefill_compute_tokens": 9363.0, "structural_new_tokens": 7246, "eviction_tokens": 2117.0, "best_possible_share": 0.9768008477967849}}
