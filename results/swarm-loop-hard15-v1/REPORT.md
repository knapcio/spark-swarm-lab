# Loop watchdog (swarm-loop-hard15-v1)

Plans `SWARM_LOOP_HARD15_D_PLAN.json` and `SWARM_LOOP_HARD15_L_PLAN.json` were frozen and pushed before the fresh corpus
arithmetic-hard-v15 was generated. Fable round-2 idea 3. Both arms run the default policy roll12strategy; L uses the
worker variant `xl_forced_watchdog` (branch research/xl-watchdog-v1): a thinking stream whose last 2,000 characters
compress below a zlib ratio of 0.06 twice in a row (checked every 500 characters) is stopped and its answer forced, as
after a length cut; the failed agent is replaced as usual. Inkling-2-Mini x4, mem fraction 0.75, each arm alone.

## Result

| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Loop stops (plans, accepted) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| D: default (no watchdog) | **85** | 0 | 11 | 79,542 | 125 min | 227.3 | 2.67 | 0 (0, 0) |
| L: default + loop watchdog | **83** | 0 | 13 | 73,021 | 102 min | 195.7 | 2.36 | 102 (102, 0) |

L vs D paired: +1 / -3 (p = 0.625); L/D tokens 0.918, wall 0.813.

Frozen decision rule: zero_wrong = True, solved_at_least_d_minus_2 = True, tokens_at_most_95pct = True, adopt_watchdog = True

Amendment (2026-11-23, before arm L finished): arm D case eva-h247d88a63ba seed 1 lost one judge request to a transient upstream disconnect on Spark_03 (shim_upstream_errors 1, no container restart); per the frozen resume rule it was rerun with the same seeds in segment `-resume1` after arm L. This report script (frozen sha256 1812e6a68a36) was changed only to merge resume segments and to count wrong answers in superseded infra attempts against the arm; the runtime code is unchanged.

D wall, energy and tokens include the resume segment (one case, 25 min). Frozen rule outcome: adopt.

**Mechanism.** In L the watchdog stopped 102 thinking streams; all 102 forced answers were rejected by the judge
(0 accepted), so a stopped agent is simply replaced earlier. The tokens it saves are the rest of each loop:
9.8 % of D's completed plan-stream characters lie after the point where the watchdog would have stopped them.
Measured L/D server tokens: 0.918 with the frozen accounting, which charges D the wasted infra attempt of
eva-h247d88a63ba s1 plus its rerun; without that waste 0.966 (-3.4 %),
a sensitivity estimate (it removes the resume segment, which has the size of the faulted attempt), which would not pass
the 0.95 gate. The accuracy side: offline replay of the same detector on 708 streams from 13 arms that ran without
it (`inkling/replay_loop_watchdog.py`, [replay.json](replay.json); it checks exact 500-character steps, the online detector
checks arriving chunks, so the replay is approximate) finds 9 streams that met the stop criterion and later gave the
accepted, correct answer of their case. 8 of these 9 ran to the thinking-budget limit and then received a forced answer;
one closed its thinking normally. So these are not shown to be streams that escaped their loop: the observed contrast is a
forced answer at loop detection (0 of 102 accepted in L) versus a forced answer at the budget limit (8 accepted
in the replay), and whether those cases would be lost under the watchdog is not established. A trigger of at least
54 consecutive checks would have spared all 9 in this replay (99 stops instead of 708); that threshold is fitted to these
data and untested. In this study 2 of L's 3 lost cases are cases whose D-winning agent looped in L and was stopped.

**Verdict: provisionally not adopted.** The frozen rule passed; this is a policy decision under the owner's
quality-first priority, not a failed pre-registered test. The independent review (astra, 2026-11-23) suggests the fair
follow-up: validate the detector on recorded chunk boundaries, then a prospective three-arm study with no intervention,
the forced answer, and one bounded "change approach" nudge, with frozen cost accounting and case-level accuracy criteria.

Files: worker `forced72.py` on research/xl-watchdog-v1, `inkling/arms.py`, `inkling/report_loop_hard15.py`, numbers in [report.json](report.json).
