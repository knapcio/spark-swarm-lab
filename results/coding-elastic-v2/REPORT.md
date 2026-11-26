# coding-elastic-v2: elastic answer reserve in the coding swarm (R2, code_elastic)

| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | cut-off answers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | complete | 72 | 70 | 2 | 0 | 1,867,590.0 | 25,938.8 | 2,374.6 | 65.9 | 0.9416 | 12 |
| A | complete | 72 | 70 | 2 | 0 | 1,681,568.0 | 23,355.1 | 2,153.5 | 58.2 | 0.8317 | 0 |

Paired (72 cases): reserve-only solved 2, plain-only 2, exact sign test p = 1.

P answer paths: {"finished": 92, "self_closed": 81, "answer_cut": 12, "answer_cut_failed": 12, "forced": 11}
P wrong answers: [{"task_id": "eva-json_select", "seed": 41, "agent": 2, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-spreadsheet_eval", "seed": 40, "agent": 4, "path": "forced", "answer_steps": 1, "answer_cut": false}]

A answer paths: {"finished": 85, "self_closed": 72, "answer_cut": 0, "answer_cut_failed": 0, "forced": 12, "continued": 1}
A wrong answers: [{"task_id": "eva-shell_words", "seed": 40, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-shell_words", "seed": 42, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}]

## Decision (complete inputs, unrounded values)

Rules: {"P": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py).", "A": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py)."}

Evaluation: {"unanswered_at_most_plain": true, "solved_at_least_plain_minus_1": true, "wrong_at_most_plain_plus_1": true, "tokens_at_most_100pct": true, "reserve_adopted": true}

## Disclosures

The reserve is one transport rule on finish_reason (no task content, no prompt change): an answer cut by length is continued in the same sequence in 2,048-token steps, at most 10,240 answer tokens, every step charged and reported. code_elastic raises the per-agent cap by 25 % (40,960 instead of 32,768; the extra 8,192 tokens are usable by the answer phase only), declared in the A plan's limits; any comparison against other systems must state it.
Neither worker has a transport retry. Acceptance is the public feedback cases; the hidden holdout cases only score. Tokens are server counters over each arm's window. Idea: IDEAS-swarm-round5-fable.md, idea 1.

## Outcome

Replication of [coding-elastic-v1](../coding-elastic-v1/REPORT.md) on fresh seeds 40-42 (plans re-pinned to the current
runner files, 1bb16f0): the same frozen rule is met again (70 / 2 wrong vs 70 / 2; tokens 0.90x, wall 0.91x, 0.83 vs
0.94 Wh per solved; 0 cut-off answers vs 12). Pooled over v1 and v2: code_elastic 140 solved / 4 wrong vs plain R2
141 / 3 of 144. **code_elastic becomes the coding default** (R2 with code_elastic: first call 30,720 as before; a
length-cut answer continues in 2,048-token steps, total <= 40,960 per agent, every token charged). Disclosed: the
per-agent cap is 25 % higher than code_xl's, and the pooled wrong count is one higher (4 vs 3), within the frozen rule.
Report run via .runtime/report_rep.py (pinned report_reserve_coding.py, study/plans repointed).

