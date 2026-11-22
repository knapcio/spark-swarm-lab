# Three agents in flight instead of four (swarm-width3-hard11-v1)

Plan [`SWARM_WIDTH3_HARD11_PLAN.json`](../../SWARM_WIDTH3_HARD11_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v11 (generator seed 2026112107) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **D roll8strategy** (default since [hard10](../swarm-strategy-hard10-v1/REPORT.md)): 4 agents in flight; every agent ending
  without an accepted plan is replaced by a fresh-seed agent with a strategy hint, up to 8; the first accepted plan cancels the rest.
- **D3 roll3strategy**: identical with 3 agents in flight.

## Result

| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | Case wall median / p90 | GPU Wh | Wh per solved | Agents per case | Escalated cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D roll8strategy (4 in flight, default) | **83** | 0 | 13 | 61,183 | 79 min | 327 / 2666 s | 150.3 | 1.81 | 4.72 | 20 |
| D3 roll3strategy (3 in flight) | **81** | 0 | 15 | 71,585 | 114 min | 371 / 4015 s | 206.4 | 2.55 | 4.18 | 26 |

D3 vs D paired: +2 / -4 (p = 0.688); D3/D tokens 1.17, wall 1.441, energy 1.373.

Frozen decision rule: zero_wrong = True, tokens_at_most_90pct = False, solved_at_least_d_minus_2 = True, wall_at_most_110pct = False, adopt_roll3strategy = False

**roll8strategy (4 in flight) stays the default** (tokens_at_most_90pct, wall_at_most_110pct, adopt_roll3strategy).

Why 3 in flight costs more, not less: with fewer agents racing, the first accepted plan arrives later, so the agents that
are cancelled have already run longer, and more cases fall through to escalation (failing agents use their whole budget).
Caveat (design, stated before the results were read): both arms ran 20 cases at once, so D3 kept only ~15 agents per node
busy (and unevenly: 3 agents per case over 4 nodes), which inflates its wall time; its token count is not affected by
that and is already higher than D's. In the coding swarm the opposite held (coding-stagger-v1), because there the
first passing proposal usually arrives before the second wave would start.

Files: `run_variants.py` (`roll3strategy`), `inkling/arms.py`, `inkling/report_width3_hard11.py`, numbers in [report.json](report.json).
