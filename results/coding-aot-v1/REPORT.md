# coding-aot-v1: Atom of Thoughts in the coding swarm (R2)

| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P (code_xl) | complete | 72 | 68 | 4 | 0 | 1,561,018.0 | 21,680.8 | 1,447.0 | 43.7 | 0.6428 | 0 |
| A (code_aot) | complete | 72 | 66 | 3 | 3 | 3,864,343.0 | 53,671.4 | 4,154.9 | 117.3 | 1.777 | 0 |

Paired (72 cases): AoT-only solved 3, plain-only 5, exact sign test p = 0.7266.

AoT agents: {"agents": 101, "round1_decomposed": 101, "aux_failure": 0, "contracted": 101, "with_facts": 101, "facts": 230, "winners_with_facts": 69, "no_summary": 69}

## Decision (complete inputs, unrounded values)

Rules: {"P": "AoT is adopted if A solved >= P solved + 3, A wrong <= P wrong, A server tokens <= 1.10 x P (complete pairing).", "A": "AoT is adopted if A solved >= P solved + 3, A wrong <= P wrong, A server tokens <= 1.10 x P (complete pairing)."}

Evaluation: {"solved_at_least_plain_plus_3": false, "wrong_at_most_plain": true, "tokens_at_most_110pct": false, "AoT_adopted": false}

## Disclosures

Transport: the pinned coding worker transport has no completion retry in either variant (code_xl and code_aot are identical there): a lost request is an operational fault for both arms, and no retry tokens exist to charge on either side. An auxiliary AoT failure ends the AoT loop; the agent's final call still runs. Acceptance is the public feedback cases; the hidden holdout cases only score. Both arms use the same worker source revision, per-agent completion-token budget (32,768) and agent count, so the compute cap is equal; tokens are server counters over each arm's window.

Atom of Thoughts: Teng et al. 2025 (arXiv 2502.12018, github.com/qixucen/atom); the task-graph framing follows alkimiadev's taskgraph idea.
