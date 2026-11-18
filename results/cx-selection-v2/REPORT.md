# Cross-execution vote for the coding swarm (CX): negative result

Plan `CX_SELECTION_PLAN.json` (frozen before any call; erratum_1: v1 had a loader bug that dropped agents 4-7 and lost inputs on cut answers, v2 fixes both, rule unchanged). Candidates: the frozen code of the 8 x 32K coding agents (coding-hard-xl-v1 + v1b + ext-v1). For each of the 55 cases with at least two distinct feedback-passing programs, one Nemotron thinking call wrote test inputs from the public task only (median 24 inputs; 2 cases got none); every feedback-passing program ran on them in the pinned CPU sandbox; the selection was the largest group with identical outputs (ties -> group with the earliest agent). Hidden holdout results scored the frozen selections. Infrastructure faults: 0.

| 72 cases | first agent passing feedback (current rule) | CX vote | oracle (any agent correct) | DeepSeek 1 call |
|---|---:|---:|---:|---:|
| 4 agents | 51 | 51 | 59 | 61 |
| 8 agents | 56 | 55 | 64 | 61 |

Why it does not help (case inspection, 8 agents): the model-written inputs often do not separate correct from wrong programs (one group mixes correct and wrong agents, e.g. ledger, common_free_slots s2), wrong programs sometimes agree with each other and outvote a lone correct one (decode_repeat s1), and 4-4 ties fall back to the earliest agent. It wins one case (ledger s2) and loses two.

Reading: on these tasks, majority agreement on self-generated inputs is not a better arbiter than "first program that passes the public tests". The remaining coding gap to DeepSeek (56 vs 61, oracle 64) needs better discrimination: inputs targeted at the disagreement between candidates, or a trusted reference, not plain voting.
