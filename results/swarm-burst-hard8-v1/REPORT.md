# Escalate earlier and further? (swarm-burst-hard8-v1)

Plan [`SWARM_BURST_HARD8_PLAN.json`](../../SWARM_BURST_HARD8_PLAN.json) was frozen and pushed (4eb69e7) before the fresh
corpus arithmetic-hard-v8 (generator seed 2026112104) was generated (b977f0b). Inkling-2-Mini on Spark_01..04
(mem fraction 0.75), 96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU energy.

- **B+ roll8cancel** (default since [hard7](../swarm-escalate-hard7-v1/REPORT.md)): 4 in flight, failures replaced, up to 8.
- **B++ roll12burst**: up to 12 agents, and if nothing is accepted 900 s after the case started, 8 in flight instead of 4.

## Result

| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts (false) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B+ roll8cancel (default) | **91** | 0 | 5 | 47,278 | 66 min | 325 / 1563 / 2903 s | 123.7 | 1.36 | 44 | 0 (0) |
| B++ roll12burst (cap 12, burst at 900 s) | **90** | 0 | 6 | 70,657 | 91 min | 458 / 2280 / 3663 s | 174.7 | 1.94 | 125 | 21 (9) |

B++ vs B+ paired: +2 / -3 (p = 1). Late rescues in B++ (answered by agents 9-12, which B+ never runs): 4 (4 correct). Answering slot histogram B++: {0: 19, 1: 21, 2: 23, 3: 21, 4: 0, 5: 1, 6: 0, 7: 1, 8: 0, 9: 2, 10: 0, 11: 2}.

Frozen decision rule: zero_wrong = True, tokens_at_most_115pct = False, late_rescues_at_least_2 = True, wall_at_most_90pct = False, adopt_roll12burst = False

- Escalating further does find answers B+ cannot: 4 cases were answered (correctly) by agents 9-12. But B++ ended
  with 90 solved vs 91 (paired +2 / -3): the extra rescues are within run-to-run noise.
- The time trigger is the problem under a loaded fleet: it fired in 21 cases, 9 of them later answered by one of the
  first four agents. Burst agents compete with every other case for the same slots, so the median case took
  458 s instead of 325 s, the arm took 91 instead of 66 min, and server tokens per case rose
  49 % (1.94 vs 1.36 Wh per solved case).

Frozen rule: B++ replaces B+ if 0 wrong, tokens <= 1.15 x B+ and (>= 2 late rescues or wall <= 0.90 x B+).
zero_wrong = True, tokens_at_most_115pct = False, late_rescues_at_least_2 = True, wall_at_most_90pct = False, adopt_roll12burst = False.

**B+ stays the default**: tokens_at_most_115pct, wall_at_most_90pct, adopt_roll12burst. Escalation should stay failure-driven (B+); a time trigger only pays when the fleet has idle capacity.

Files: `run_variants.py` (`roll12burst`), `inkling/arms.py`, `inkling/report_burst_hard8.py`, numbers in [report.json](report.json).
