# Deep agents on hard fresh tasks (arithmetic-hard-v1 evaluation, 48 tasks x 3 seeds)

Agent type chosen on the hard development split (depth-hard-dev-v1) and frozen before this run (CONFIRM_HARD_LONG_PLAN.json). Same tasks and seeds as confirm-hard-v1; separate run the same day, same runtime, no wall-clock limits.

| Method (independent agents, any verified plan wins) | Ceiling per case | Solved / 144 | Actual completion tokens per case |
|---|---:|---:|---:|
| Original method: 4 x plain_original (8K) | 32,768 | 57 | n/a (see confirm-hard-v1) |
| Short swarm: 8 x forced_explicit (8K) | 65,536 | 81 | 55,886 |
| **Deep agents: 4 x long_forced_original (16K)** | 64,000 | **99** | **49,671** |

Paired by case, deep any-of-4 minus short any-of-8: task-cluster bootstrap 95% interval +2.8 to +22.9 percentage points. 4-number tasks 64 vs 50; 6-number tasks 35 vs 31. Single deep agent 212/576 (36.8%), mean 12,418 completion tokens. Union of both runs (hindsight, not a method): 111/144.

Errors [], 0 deadlines, 0 infrastructure failures, wall 4,338 s at 12 agents per replica. Cross-run comparison: run order and server load differ; neither has a wall-clock cutoff.
