# coding-elastic-v1: elastic answer reserve in the coding swarm (R2, code_elastic)

| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | cut-off answers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | complete | 72 | 71 | 1 | 0 | 1,718,895.0 | 23,873.5 | 2,087.7 | 55.7 | 0.7845 | 5 |
| A | complete | 72 | 70 | 2 | 0 | 1,595,361.0 | 22,157.8 | 1,445.8 | 43.8 | 0.625 | 0 |

Paired (72 cases): reserve-only solved 1, plain-only 2, exact sign test p = 1.

P answer paths: {"finished": 82, "self_closed": 75, "answer_cut": 5, "answer_cut_failed": 5, "forced": 7}
P wrong answers: [{"task_id": "eva-json_select", "seed": 39, "agent": 0, "path": "self_closed", "answer_steps": 0, "answer_cut": false}]

A answer paths: {"finished": 80, "self_closed": 75, "answer_cut": 0, "answer_cut_failed": 0, "forced": 4, "continued": 1}
A wrong answers: [{"task_id": "eva-shell_words", "seed": 38, "agent": 0, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-shell_words", "seed": 39, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}]

## Decision (complete inputs, unrounded values)

Rules: {"P": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py).", "A": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py)."}

Evaluation: {"unanswered_at_most_plain": true, "solved_at_least_plain_minus_1": true, "wrong_at_most_plain_plus_1": true, "tokens_at_most_100pct": true, "reserve_adopted": true}

## Disclosures

The reserve is one transport rule on finish_reason (no task content, no prompt change): an answer cut by length is continued in the same sequence in 2,048-token steps, at most 10,240 answer tokens, every step charged and reported. code_elastic raises the per-agent cap by 25 % (40,960 instead of 32,768; the extra 8,192 tokens are usable by the answer phase only), declared in the A plan's limits; any comparison against other systems must state it.
Neither worker has a transport retry. Acceptance is the public feedback cases; the hidden holdout cases only score. Tokens are server counters over each arm's window. Idea: IDEAS-swarm-round5-fable.md, idea 1.

## Run note and status

Arm P first stopped at 06:32Z on one infrastructure fault (a ServerDisconnectedError at request start on Spark_02,
46 ms after the request began; no server error or restart; this worker has no transport retry). That run is kept as
runs/coding-elastic-v1-p-infrafail1 and is not used; both arms were rerun in full under the unchanged frozen plans
(fa26531) from 06:37Z. Report run via .runtime/report_rep.py (pinned report_reserve_coding.py, study/plans repointed).

Status: the frozen rule is met, at its margins (A 70 / 2 wrong vs P 71 / 1, tokens 0.93x). This is the same shape as
coding-reserve-v1, whose adoption the replication reversed, so **code_elastic is not the default** until a replication
on fresh seeds passes the same rule. The replication (seeds 40-42) is queued behind the live-collaboration screens.

