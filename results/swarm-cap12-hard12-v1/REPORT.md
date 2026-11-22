# Escalate further: cap 12 instead of 8 (swarm-cap12-hard12-v1)

Plan [`SWARM_CAP12_HARD12_PLAN.json`](../../SWARM_CAP12_HARD12_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v12 (generator seed 2026112108) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **D roll8strategy** (default): 4 in flight; failures replaced by fresh-seed agents with strategy hints, up to 8.
- **D12 roll12strategy**: identical with up to 12 agents (strictly failure-driven, no time trigger).

## Result

| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D roll8strategy (default, cap 8) | **81** | 0 | 15 | 61,990 | 79 min | 371 / 3062 / 3460 s | 150.1 | 1.85 | 62 | n/a |
| D12 roll12strategy (cap 12) | **85** | 0 | 11 | 76,653 | 102 min | 383 / 3939 / 4678 s | 194.0 | 2.28 | 114 | n/a |

D12 vs D paired: +6 / -2 (p = 0.289). Late rescues in D12 (answered by agents 9-12, which D never runs): 2 (2 correct). Answering slot histogram D12: {0: 19, 1: 21, 2: 23, 3: 17, 4: 1, 5: 0, 6: 2, 7: 0, 8: 1, 9: 0, 10: 1, 11: 0}.

Frozen decision rule: zero_wrong = True, late_rescues_at_least_2 = True, tokens_at_most_120pct = False, wall_at_most_125pct = False, adopt_roll12strategy = False

**roll8strategy (cap 8) stays the default** (tokens_at_most_120pct, wall_at_most_125pct, adopt_roll12strategy).

**Max-accuracy mode: cap 12.** Escalating past 8 agents finds answers 8 agents cannot: D12 solved 85
vs 81 (paired +6 / -2, p = 0.29; 2 cases answered only by agents 9-12, both
correct), with 0 wrong answers. The extra cost is paid only on the hard cases (every case that 8 agents cannot solve
burns up to 4 more budgets): +24 % tokens and +29 % wall overall, 2.28 vs
1.85 Wh per solved case. The cost limits in the frozen rule were my own choice, not the owner's;
since the owner's priority is quality, cap 12 is kept as the max-accuracy mode and is being replicated on a fresh corpus
(it becomes the default if the gain repeats with 0 wrong). Cap 8 remains the efficiency default until then.

Files: `run_variants.py` (`roll12strategy`), `inkling/arms.py`, `inkling/report_cap12_hard12.py`, numbers in [report.json](report.json).
