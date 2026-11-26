# swarm-fair-hard23-v1

| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated | total compute | wall s | Wh | Wh/solved |
|---|---|---|---|---|---|---|---|---|---|---|---|
| W | roll12wide | complete | 96 | 86 | 0 | 10 | 7,171,385.0 | 7,351,267.0 | 4,316.0 | 146.3 | 1.701 |
| F | roll12fair | complete | 96 | 88 | 0 | 8 | 6,421,734.0 | 6,567,531.0 | 4,012.6 | 135.5 | 1.54 |

Paired: F-only solved 4, W-only 2, exact sign test p = 0.6875.

## Time to an answer (s; mean / median / p90)

- W from case start: 418.7 / 300.1 / 671.7 (n = 86)
- W from segment start: 1,302.1 / 1,071.8 / 2,574.0 (n = 86)
- F from case start: 837.5 / 567.4 / 1,953.0 (n = 88)
- F from segment start: 837.5 / 567.4 / 1,953.0 (n = 88)
- W max agents in flight per case: {'4': 84, '5': 2, '6': 2, '7': 2, '8': 6}
- F max agents in flight per case: {'1': 45, '2': 24, '3': 6, '4': 4, '5': 4, '6': 2, '7': 7, '8': 4}; median time to the first failure 1,212.8 s

Facts (F / W): {"wall_ratio_f_over_w": 0.9297014710747111, "generated_tokens_ratio": 0.8954663569171087, "total_compute_ratio": 0.8933876296426181, "wh_ratio": 0.9261208310552214}

## Decision (complete inputs, unrounded values)

Rule: F (roll12fair) replaces W (roll12wide) if F has 0 wrong, F solved >= W - 2, F arm wall <= 0.95 x W and F server tokens <= 1.00 x W (exact).

Evaluation: {"zero_wrong": true, "solved_within_noise": true, "wall_at_most_95pct_of_W": true, "tokens_at_most_100pct_of_W": true, "F_replaces_W": true}

## Wrong answers over all attempts and wasted work

- W: 0 wrong attempt(s)
- F: 0 wrong attempt(s)

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.

Design notes: (1) W and F run the same agents with the same prompts and seeds (slot s of a case has the same seed in both arms); F only changes which case gets a free agent slot and when: every case is open from the start, a free slot (a node below its cap minus 2 permits kept for judges) goes to the case with the fewest agents in flight (ties: fewest started, then the earlier case), at most 4 in flight before the case's first failed agent and 8 after, never beyond 12 agents; an F agent may run on another node than in W; (2) the rule reads slot counts and failure counts only, never elapsed time or task content; (3) time to answer from the segment start is comparable between arms only within one segment (a resumed segment restarts its clock).

Idea: IDEAS-swarm-round5-fable.md, idea 2 (water-filling admission).

## Outcome

Replication of [swarm-fair-hard22-v1](../swarm-fair-hard22-v1/REPORT.md) on a fresh corpus (hard-v23), same plan and
rule: **passed** (F 88 vs W 86, 0 wrong in both; wall 0.93x, tokens 0.90x, energy 0.93x). Pooled with hard-v22: F 170 vs
W 166 of 192, 0 wrong; wall 0.91x and 0.93x. **roll12fair stays the arithmetic default for batch runs.**

Two facts that go with it:
- The per-case latency cost appears only in batches: with every case open at once, a case shares agent slots with the
  others, so its time to an answer rises (median 567 s vs 300 s here, 475 s vs 218 s on hard-v22). The gain is batch
  wall, tokens and energy.
- Single-task use is unaffected by construction: with one case there is nothing to share, and both policies apply the
  same limits (4 in flight before the first failed agent, 8 after, cap 12). This was not measured separately.

Report run via .runtime/report_rep.py (pinned report_fair.py with STUDY and PLAN repointed; it reproduces the hard-v22
report byte for byte).
