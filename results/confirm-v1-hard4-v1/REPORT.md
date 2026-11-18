# Swarm v1 (16K deep4) on arithmetic-hard-v4, seeds 1-2

Plan `CONFIRM_V1_HARD4_PLAN.json` (frozen and committed 19f4cf3 before any call; owner request for the article's headline chart). Same 48 tasks and seeds as Swarm v2 (`confirm-xl-hard4-v2` seed 1, `confirm-xl-hard4-seed2-v1` seed 2). Agent `long_forced_original` (14848 thinking / 16000 total) from source d94c893, 16K serving originals, 4 agents per case, Nemotron thinking judge selects (first accepted plan). Errors [], infrastructure faults 0, deadlines 0, wall 2,983 s.

| hard-v4, 96 cases (48 tasks x 2 seeds) | Solved | Wrong answers | No answer | Mean completion tokens / case |
|---|---:|---:|---:|---:|
| One Nemotron (32K, agent 0 of Swarm v2) | 54 | | | |
| **Swarm v1: deep4 16K, own judge** | **66** | 0 | 30 | 61,250 |
| Swarm v2: deep4 32K, own judge | 82 | 0 | 14 | |
| One DeepSeek (32K) | 85 | | | |

Seed 1: 33/48, seed 2: 33/48. Oracle (any agent correct): 67/96. Paired Swarm v2 vs Swarm v1: +17 / -1.

Reading: on the fresh hard-v4 tasks the 32K thinking budget is worth 16 cases over the same swarm at 16K (66 -> 82 of 96), consistent with hard-v3 (31 -> 38 of 48). Neither swarm gave a wrong answer.
