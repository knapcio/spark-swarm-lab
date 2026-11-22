# Coding swarm: start 4 agents, add 4 only if needed (coding-stagger-v1)

Plans [`CODING_STAGGER_S44_PLAN.json`](../../CODING_STAGGER_S44_PLAN.json) and [`CODING_STAGGER_E8_PLAN.json`](../../CODING_STAGGER_E8_PLAN.json)
were frozen and pushed before any call with seeds 7-9 on coding-hard-v1 (24 evaluation tasks x 3 fresh seeds = 72 cases,
agent seed offset 2700). Both arms use the coding default since [coding-earlystop-v1](../coding-earlystop-v1/REPORT.md):
the first proposal passing all public feedback cases ends the case. Inkling-2-Mini, mem fraction 0.75, 20 agents per
node, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **E**: all 8 agents queued at once.
- **S**: agents 1-4 first; agents 5-8 start only if no proposal has passed 300 s after the case's first agent started,
  or as soon as all of the first four have finished without a pass.

## Result

| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy | Wh per solved | Stop median / p90 | Cases with agents 5-8 | Cancelled / never started |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E: all 8 at once (default) | **69** | 59,849 | 60 min | 114.47 Wh | 1.66 | 315 / 939 s | 72 | 491 / 0 |
| S: 4 first, 4 more after 300 s | **69** | 50,019 | 52 min | 98.18 Wh | 1.42 | 388 / 1099 s | 39 | 365 / 132 |

S vs E paired: +3 / -3 (p = 1); S/E tokens 0.836, wall 0.867, energy 0.858.

Frozen decision rule: tokens_at_most_85pct = True, solved_at_least_e_minus_2 = True, wall_at_most_110pct = True, adopt_stagger = True

**The staggered start becomes the coding default.**

Files: `run_coding_earlystop.py` (`stagger`), `inkling/coding_arms.py`, `inkling/report_coding_stagger.py`,
numbers in [report.json](report.json).
