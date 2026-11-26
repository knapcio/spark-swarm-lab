# coding-reserve-v2: elastic answer reserve in the coding swarm (R2, code_reserve)

| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | cut-off answers |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | complete | 72 | 71 | 1 | 0 | 1,601,520.0 | 22,243.3 | 2,451.5 | 60.8 | 0.8559 | 8 |
| A | complete | 72 | 66 | 6 | 0 | 1,419,031.0 | 19,708.8 | 1,238.9 | 37.6 | 0.5695 | 0 |

Paired (72 cases): reserve-only solved 0, plain-only 5, exact sign test p = 0.0625.

P answer paths: {"finished": 85, "self_closed": 76, "answer_cut": 8, "answer_cut_failed": 8, "forced": 9}
P wrong answers: [{"task_id": "eva-shell_words", "seed": 32, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}]

A answer paths: {"finished": 78, "self_closed": 70, "answer_cut": 0, "answer_cut_failed": 0, "forced": 7, "continued": 1}
A wrong answers: [{"task_id": "eva-date_diff_ymd", "seed": 32, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-shell_words", "seed": 32, "agent": 0, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-shell_words", "seed": 33, "agent": 0, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-json_select", "seed": 32, "agent": 0, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-json_select", "seed": 31, "agent": 1, "path": "self_closed", "answer_steps": 0, "answer_cut": false}, {"task_id": "eva-spreadsheet_eval", "seed": 32, "agent": 1, "path": "forced", "answer_steps": 1, "answer_cut": false}]

## Decision (complete inputs, unrounded values)

Rules: {"P": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py).", "A": "A adopted if A unanswered <= P, A solved >= P - 1, A wrong <= P + 1, A server tokens <= 1.00 x P (report_reserve_coding.py)."}

Evaluation: {"unanswered_at_most_plain": true, "solved_at_least_plain_minus_1": false, "wrong_at_most_plain_plus_1": false, "tokens_at_most_100pct": true, "reserve_adopted": false}

## Disclosures

The reserve is one transport rule on finish_reason (no task content, no prompt change): an answer cut by length is continued in the same sequence in 2,048-token steps, at most 10,240 answer tokens, every step charged and reported. code_reserve keeps the 32,768-token agent budget (thinking cap 26,624).
Neither worker has a transport retry. Acceptance is the public feedback cases; the hidden holdout cases only score. Tokens are server counters over each arm's window. Idea: IDEAS-swarm-round5-fable.md, idea 1.

## Outcome

Replication of [coding-reserve-v1](../coding-reserve-v1/REPORT.md) (adopted 2026-11-26 on seeds 28-30) on fresh seeds 31-33, same plans and rule: **failed** (A 66 / 6 wrong vs P 71 / 1). The code_reserve adoption is **reverted**; the coding default is plain R2 (code_xl) again.

**Investigation (before any retry).** The two arms differ in one more setting than the reserve rule: code_reserve caps the first call at 26,624 thinking tokens, code_xl at 30,720 (coding_forced.py CAPS; budget-neutral by design, total 32,768 in both). Otherwise the plans are identical apart from the variant: same worker source 2b0195e, prompts (prompt_ids_sha256 equal for all 144 v2 / 142 v1 agent pairs), request seeds and request bodies other than max_tokens. The same-seed pairing does not reproduce on this serving, though: every P/A agent pair diverges within the first 8-101 characters (median about 60), and none of the 42 v2 agents that finished in both arms produced identical code. Each arm is therefore an independent sample, not a paired replay. Five of the six wrong answers in A are self-closed answers below either cap, with no reserve step; the sixth (eva-spreadsheet_eval s32 a1) was forced at the 26,624 cap and is the only one the lower cap touches directly (the same slot in P closed itself at 23,462 tokens and was right). Acceptance order is not the cause: in all five flipped cases the same agent slot won in both arms, and only the drawn sample differed. Paired by task, seed and slot, thinking length shows no shift (A/P geomean 0.96 in v1 and 1.02 in v2; A shorter in 41 of 70, sign p = 0.19). The faster A wall comes from fewer agents started (78 vs 85) and no cut-answer second calls. Pooled over v1 and v2: P 141 solved / 3 wrong, A 137 / 7; discordant cases plain-only 5, reserve-only 1 (p = 0.22); holdout failures among feedback passes P 3/145, A 7/144. Conclusion: no mechanism found beyond sampling variance, plus one forced answer from the lower cap. The v1 adoption rested on one +1 case, and the replication reversed it.

Report run via .runtime/report_rep.py (pinned report_reserve_coding.py with STUDY and plan names repointed; it reproduces the v1 report byte for byte).
