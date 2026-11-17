# Swarm-variant screen (arithmetic-hard-v2 development split, 16 tasks x 3 seeds)

Arbiter-free: a Nemotron thinking judge (with a one-sentence reason) selects; the exact verifier only scores. All policies use up to 4 deep agents (16K) per case. Plan VARIANTS_SCREEN_PLAN.json (frozen before the run; first launch failed on a worker serialization bug and is kept as diagnostic).

| Policy | Solved / 48 | Wrong answers | Mean agent calls | Mean completion tokens (agents + judges) |
|---|---:|---:|---:|---:|
| deep4: 4 identical deep agents | **29** | 0 | 4.0 | 59,950 |
| strategy4: 4 deep agents, distinct strategy hints | **32** | 0 | 4.0 | 59,892 |
| repair4: sequential repair with judge critique (up to 4) | **29** | 0 | 2.5 | 41,072 |
| board2x2: shared failure board (2 + 2 agents) | **34** | 0 | 2.8 | 43,589 |

strategy4 vs deep4, paired: wins 4, losses 1

repair4 vs deep4, paired: wins 2, losses 2

board2x2 vs deep4, paired: wins 5, losses 0

Selection rule (frozen): most solved -> board2x2 goes to the fresh hard-v3 confirmation with deep4 as control. Small sample (48 cases); differences are suggestive, not established. Errors [], wall 6014 s.
