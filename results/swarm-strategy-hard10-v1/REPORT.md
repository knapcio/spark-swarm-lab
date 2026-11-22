# Escalation agents with distinct strategy hints (swarm-strategy-hard10-v1)

Plan [`SWARM_STRATEGY_HARD10_PLAN.json`](../../SWARM_STRATEGY_HARD10_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v10 (generator seed 2026112106) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **B+ roll8cancel** (default): failed agents are replaced by fresh-seed agents (up to 8), first accept cancels the rest.
- **S roll8strategy**: identical, but escalation agent k (slots 4-7) gets strategy hint k (work backward from the target,
  a product close to the target, use every number, one large intermediate first).

## Result

| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Escalated cases | Escalation agents (accepted) | Strict rescues | Judge false accepts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B+ roll8cancel (default) | **83** | 0 | 13 | 58,326 | 77 min | 145.9 | 1.76 | 19 | 65 (2) | 1 | 0 |
| S roll8strategy (escalation agents get strategy hints) | **86** | 0 | 10 | 55,395 | 72 min | 137.3 | 1.60 | 16 | 60 (5) | 4 | 0 |

S vs B+ paired: +5 / -2 (p = 0.453).

Frozen decision rule: zero_wrong = True, more_strict_rescues = True, higher_escalation_success = True, tokens_at_most_110pct = True, adopt_roll8strategy = True

**roll8strategy becomes the default.** The counts behind it are small (5 vs 2 accepted escalation agents, 4 vs 1 strict rescues) and the paired solved
difference is within run-to-run noise, but by mechanism the hints only change agents that start after a failure, so the
first four agents and every case they solve are untouched; together with swarm-repair-hard9-v1 (critiques halved the
escalation success) the picture is consistent: escalation agents should be fresh and diverse, not anchored.

Files: `run_variants.py` (`roll8strategy`), `inkling/arms.py`, `inkling/report_strategy_hard10.py`, numbers in [report.json](report.json).
