# Coding R2 replication (coding-roll2-v1)

Plans `CODING_ROLL2_S_PLAN.json` and `CODING_ROLL2_R2_PLAN.json` (9636ea2) were frozen before any call with seeds 16-18 on
coding-hard-v1. Generic mechanism (owner rule 2026-11-24). Early stop in both arms; each arm alone on Inkling-2-Mini x4.

| Arm | Solved /72 | Wrong | Server tokens/case | Arm wall |
|---|---:|---:|---:|---:|
| S: early stop + stagger 4+4 at 300 s | **68** | 3 | 49,554 | 49 min |
| R2: replace failures, 2 in flight (default) | **71** | 1 | 25,875 | 52 min |

R2 vs S paired: +4 / -1 (p = 0.375). Frozen rule (R2 stays if wrong <= S + 1, solved >= S - 2, fewer tokens): {'wrong_ok': True, 'solved_ok': True, 'fewer_tokens': True, 'r2_stays': True}.

**R2 is confirmed as the coding default.** Pooled with coding-roll-v1 (seeds 13-15): R2 142 vs S 133 of 144, wrong 2 vs 8,
about half the tokens. A wrong coding answer passes the public tests and fails the hidden ones; fewer agents racing to the
first public pass gives fewer of them in both replications, though the earlier pool replay attributes part of the gap to seeds.
