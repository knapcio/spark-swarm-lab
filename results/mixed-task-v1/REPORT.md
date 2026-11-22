# Arithmetic and coding swarms on the fleet at the same time (mixed-task-v1)

Plans [`MIXED_TASK_PLAN.json`](../../MIXED_TASK_PLAN.json) (with the four runner plans it names) were frozen and pushed before
the fresh corpus arithmetic-hard-v13 was generated and before any call with seeds 10-12 on coding-hard-v1. Both workloads
use today's defaults: arithmetic roll8strategy (96 cases), coding early stop + staggered start (72 cases). Inkling-2-Mini
x4, mem fraction 0.75. M ran both at once (10 + 10 client requests per node); Sa and Sc ran them alone (20 per node).

## Result

| | Mixed (M) | One after the other (Sa + Sc) |
|---|---:|---:|
| Arithmetic solved /96 (wrong) | **86** (0) | **88** (0) |
| Coding solved /72 | **67** | **65** |
| Wall for both workloads | **141 min** | **124 min** (77 + 47) |
| GPU energy for both | **266.86 Wh** | **237.6 Wh** |
| Server tokens | 9,620,719 | 9,284,082 |

In M the arithmetic swarm finished after 141 min and the coding swarm after 101 min. Paired: arithmetic M vs alone +1 / -3 (p = 0.62); coding +7 / -5 (p = 0.77).

Frozen decision rule: wall_at_most_95pct = False, energy_not_higher = False, arith_within_noise = True, coding_within_noise = True, recommend_mixed = False

**Run them one after the other** (wall_at_most_95pct, energy_not_higher, recommend_mixed).

Why: the static split. Each workload got half of the per-node concurrency for the whole run, and when the coding swarm
finished (after 101 min) the arithmetic swarm kept running alone with only 10 requests per node for the last
40 min, so part of the fleet stood idle; the long hard-case tails of both swarms do not overlap enough to make up for it.
Accuracy is unaffected by sharing (both paired differences are run-to-run noise). Sharing would need a dynamic split
(one global request budget per node handed to whichever swarm has work), which this study did not test.

Files: `inkling/mixed_arms.py` (concurrent driver), `inkling/arms.py`, `inkling/coding_arms.py`, `inkling/report_mixed_task.py`,
numbers in [report.json](report.json).
