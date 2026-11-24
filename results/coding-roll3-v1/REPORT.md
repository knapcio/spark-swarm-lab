# Coding R2 vs R1 (coding-roll3-v1)

Plans `CODING_ROLL3_R2_PLAN.json` and `CODING_ROLL3_R1_PLAN.json` (5a6da39), frozen before any call with seeds 19-21 on coding-hard-v1.
Generic mechanism. Early stop; failure-driven replacement with 2 (R2, default) vs 1 (R1) agents in flight; each arm alone.

| Arm | Solved /72 | Wrong | Server tokens/case | Arm wall | Stop median / p90 |
|---|---:|---:|---:|---:|---:|
| R2 (default) | **67** | 4 | 29,250 | 59 min | 476 / 1441 s |
| R1 | **66** | 6 | 19,677 | 76 min | 475 / 1418 s |

R1 vs R2 paired: +4 / -5 (p = 1). Frozen rule (R1 only if solved >= R2, wrong <= R2, fewer tokens): {'solved_ok': False, 'wrong_ok': False, 'fewer_tokens': True, 'r1_replaces_r2': False}.

**R2 stays the coding default.** R1 saves a third of the tokens but adds 2 wrong answers and 30 % arm wall.
