# Escalation hints on a shared first wave (swarm-hints-hard16-v1)

Plans `SWARM_HINTS_HARD16_WAVE_PLAN.json` and `SWARM_HINTS_HARD16_ESC_PLAN.json` (65ea777) were frozen and pushed before
arithmetic-hard-v16 (b079f8b) was generated. Fable round-2 ideas 4 and 5, and the recheck of the current strategy hints.
Phase 1 ran the default first wave (4 unhinted agents, cancel on accept) once on 192 six-number cases (24 evaluation tasks
x 8 seeds): 144 solved, 0 wrong, 48 cases without an accepted plan (the strict-hard cases).
Phase 2 ran four escalation-only arms on exactly those cases, each alone on the fleet: slots 4-11, 4 in flight,
failure-driven replacement, cancel on accept, the same agent and judge seeds in every arm; only the hint text differs.
Selection caveat: the cases are chosen by the swarm's own first-wave failure, so the counts are rescues, not a solved rate.

## Result

| Arm | Rescued (correct) | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | vs S (+/-, p) |
|---|---:|---:|---:|---:|---:|---:|---:|
| N: no hints | **19** | 0 | 29 | 200,561 | 119 min | 232.4 | +10 / -5, p = 0.302 |
| S: current 4 strategy hints (default) | **14** | 0 | 34 | 204,831 | 123 min | 235.7 |  |
| H02: hints 0 + 2 only | **16** | 0 | 32 | 214,765 | 125 min | 243.0 | +4 / -2, p = 0.688 |
| P: last-move partition hints | **31** | 0 | 17 | 157,077 | 96 min | 182.9 | +18 / -1, p = 7.63e-05 |

Accepted agents by hint position ((slot - 4) mod 4): {'N': {0: 3, 1: 9, 2: 2, 3: 6}, 'S': {0: 8, 1: 1, 2: 4, 3: 2}, 'H02': {0: 4, 1: 7, 2: 2, 3: 3}, 'P': {0: 9, 1: 16, 2: 1, 3: 5}}.

**Default escalation hints change to P** (confirmation on a fresh full-swarm corpus follows). N (no hints) rescued at least as many cases as S: the current hints show no measurable benefit on this corpus.

**Mechanism.** The P hints each fix one assumption about the final move and turn the six-number task into a smaller
sub-target the agent computes itself: (0) the last move subtracts a given x, so build target + x; (1) it adds x, so build
target - x; (2) it multiplies or divides by x; (3) it combines two values built from disjoint groups. Accepted P agents by
hint: 0: 0, 1: 0, 2: 0, 3: 0; the additive and subtractive last moves carry most rescues, consistent with
Fable's finding that the last move uses a single given number in 90 % of solutions (subtraction 65 %). The current hints
are generic strategies ("work backward", "product near the target", ...) and rescued fewer cases than no hint at all (S 14
vs N 19, not significant). P also used 23 % fewer tokens per case and 22 % less wall, because rescued cases stop early.
The hints are derived from a failure analysis of older corpora of the same generator; hard-v16 was generated after the
plans were frozen, so this is a fresh-corpus result, but conditional on first-wave failure (rescues, not a solved rate).
Per the frozen rule, P becomes the default escalation hint set after a full-swarm confirmation on a fresh corpus
(roll12strategy with P hints vs roll12strategy), which is queued next.

Files: `run_variants.py` (`esc_*`, `SPLIT_HINTS`), `inkling/strict_hard_cases.py`, `inkling/report_hints_hard16.py`, numbers in [report.json](report.json).
