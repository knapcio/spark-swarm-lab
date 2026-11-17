# Fresh confirmation: shared failure board vs 4 identical deep agents (arithmetic-hard-v3, 48 tasks x 3 seeds)

Plan CONFIRM_BOARD_HARD3_PLAN.json frozen before hard-v3 existed. Arbiter-free: Nemotron thinking judge selects; verifier only scores.

| Policy | Solved / 144 | Wrong answers | No answer | Mean agent calls | Mean completion tokens |
|---|---:|---:|---:|---:|---:|
| deep4 | **97** | 0 | 47 | 4.0 | 59,428 |
| board2x2 | **98** | 0 | 46 | 2.8 | 43,846 |

Paired: board wins 9, losses 8.

Reading: the dev-screen advantage of the shared board (34 vs 29, 5-0 paired) did NOT replicate in accuracy on fresh tasks (98 vs 97); what replicated is cost: the board reaches the same accuracy with about a quarter fewer tokens, because round 2 runs only when round 1 fails. Zero wrong answers in both arms.

Hybrid routing input (frozen rule): deepseek_cases.json = 46 board abstentions + 48 seed-1 tasks (union 78 cases).
