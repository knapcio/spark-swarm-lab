# swarm-fair-hard22-v1

| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated | total compute | wall s | Wh | Wh/solved |
|---|---|---|---|---|---|---|---|---|---|---|---|
| W | roll12wide | complete | 96 | 80 | 0 | 16 | 9,107,768.0 | 9,331,429.0 | 5,217.9 | 185.8 | 2.322 |
| F | roll12fair | complete | 96 | 82 | 0 | 14 | 8,194,997.0 | 8,366,306.0 | 4,734.2 | 168.7 | 2.058 |

Paired: F-only solved 5, W-only 3, exact sign test p = 0.7266.

## Time to an answer (s; mean / median / p90)

- W from case start: 393.4 / 218.0 / 561.6 (n = 80)
- W from segment start: 1,261.7 / 825.8 / 3,103.7 (n = 80)
- F from case start: 749.9 / 474.9 / 1,660.3 (n = 82)
- F from segment start: 749.9 / 474.9 / 1,660.3 (n = 82)
- W max agents in flight per case: {'4': 86, '5': 3, '8': 7}
- F max agents in flight per case: {'1': 49, '2': 18, '3': 7, '4': 5, '5': 15, '6': 2}; median time to the first failure 1,181.8 s

Facts (F / W): {"wall_ratio_f_over_w": 0.9072849046287356, "generated_tokens_ratio": 0.8997810440494312, "total_compute_ratio": 0.8965728614556249, "wh_ratio": 0.9083176312247645}

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

## Replicated

[swarm-fair-hard23-v1](../swarm-fair-hard23-v1/REPORT.md) on a fresh corpus passed the same rule (88 vs 86, 0 wrong,
wall 0.93x). roll12fair stays the default for batch runs; the per-case latency cost appears only in batches.
