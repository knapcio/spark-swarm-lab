# Inkling-2-Mini bug fixing with the whole project in context (bugbench eval18, 36 attempts)

Plan `bugbench/INKLING_LONG_PLAN.json` (frozen in 46e390f before any Inkling bugbench call; amendment 1 = scheduling only).
Same 18 planted-bug cases x seeds 1-2, same prompt as DeepSeek R (whole project in one prompt), same policies, caps,
arbiter-free selection (valid patch -> passes the project's public tests -> largest cluster of identical diffs -> earliest)
and hidden grading once after selection. Source files hash-identical to the Nemotron long-context run.
Infrastructure faults: L1F 0, L8F 0; halted False.

| 36 attempts (18 bugs x 2 seeds) | Fixed | Completion tokens / attempt | Mean wall s |
|---|---:|---:|---:|
| **One Inkling (L1F)** | **36** | 6,642 | 215 |
| Inkling swarm, 8 agents (L8F) | 36 | 60,885 | 432 |
| One Nemotron (L1F, same setup) | 26 | | |
| Nemotron swarm, 8 agents (L8F) | 35 | | |
| One DeepSeek V4.1 (R) | 36 | 2,786 | |

Reading: a single Inkling agent fixes every bug that DeepSeek fixes, with one call per attempt (no forcing, no
truncation), at about 2.4x DeepSeek's completion tokens. The 8-agent swarm adds nothing here; the task set is saturated.
