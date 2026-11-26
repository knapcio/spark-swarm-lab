# coding-reserve-v1: elastic answer reserve in the coding swarm (R2, code_reserve)

| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | cut-off answers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | complete | 72 | 70 | 2 | 0 | 1,652,992.0 | 22,958.2 | 1,831.5 | 52.0 | 0.7436 | 5 |
| A | complete | 72 | 71 | 1 | 0 | 1,356,984.0 | 18,847.0 | 1,231.3 | 36.8 | 0.5177 | 0 |

Paired (72 cases): reserve-only solved 1, plain-only 0, exact sign test p = 1.

P answer paths: {"finished": 82, "self_closed": 76, "answer_cut": 5, "answer_cut_failed": 5, "forced": 6}
P wrong answers: [{"task_id": "eva-shell_words", "seed": 28, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-decode_repeat", "seed": 29, "agent": 0, "path": "self_closed", "answer_steps": 0, "answer_cut": false}]

A answer paths: {"finished": 75, "self_closed": 68, "answer_cut": 0, "answer_cut_failed": 0, "forced": 6, "continued": 1}
A wrong answers: [{"task_id": "eva-shell_words", "seed": 28, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}]

## Decision (complete inputs, unrounded values)

Rules: {"P": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py).", "A": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py)."}

Evaluation: {"unanswered_at_most_plain": true, "solved_at_least_plain_minus_1": true, "wrong_at_most_plain_plus_1": true, "tokens_at_most_100pct": true, "reserve_adopted": true}

## Disclosures

The reserve is one transport rule on finish_reason (no task content, no prompt change): an answer cut by length is continued in the same sequence in 2,048-token steps, at most 10,240 answer tokens, every step charged and reported. code_reserve keeps the 32,768-token agent budget (thinking cap 26,624).
Neither worker has a transport retry. Acceptance is the public feedback cases; the hidden holdout cases only score. Tokens are server counters over each arm's window. Idea: IDEAS-swarm-round5-fable.md, idea 1.

## Superseded

The replication [coding-reserve-v2](../coding-reserve-v2/REPORT.md) (seeds 31-33) failed the same rule (A 66 / 6 wrong vs P 71 / 1). The adoption above is **reverted**: the coding default is plain R2 again.
