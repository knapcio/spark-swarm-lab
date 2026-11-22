# Escalation agents that see the judge's critique (swarm-repair-hard9-v1)

Plan [`SWARM_REPAIR_HARD9_PLAN.json`](../../SWARM_REPAIR_HARD9_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v9 (generator seed 2026112105) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **B+ roll8cancel** (default): failed agents are replaced by fresh-seed agents (up to 8), first accept cancels the rest.
- **R roll8repair**: identical, but each escalation agent's prompt lists every plan of this case the judge has rejected
  so far, with the judge's one-sentence reason.

## Result

| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Escalated cases | Escalation agents (accepted) | Strict rescues | Judge false accepts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B+ roll8cancel (default) | **86** | 0 | 10 | 69,107 | 88 min | 167.9 | 1.95 | 23 | 82 (9) | 8 | 0 |
| R roll8repair (escalation sees the critiques) | **83** | 0 | 13 | 69,950 | 87 min | 166.7 | 2.01 | 20 | 73 (4) | 4 | 0 |

R vs B+ paired: +3 / -6 (p = 0.508).

Frozen decision rule: zero_wrong = True, more_strict_rescues = False, higher_escalation_success = False, tokens_at_most_110pct = True, adopt_roll8repair = False

**B+ stays the default** (more_strict_rescues, higher_escalation_success, adopt_roll8repair). Showing escalation agents the failed attempts halves their success rate: they anchor on the rejected
plans instead of searching afresh (the same direction as repair4 on Nemotron, 2026-11-17). Fresh, independent
escalation agents stay. One DeepSeek on the same tasks: see [DEEPSEEK.md](DEEPSEEK.md) (when present).

Files: `run_variants.py` (`roll8repair`), `inkling/arms.py`, `inkling/report_repair_hard9.py`, numbers in [report.json](report.json).
