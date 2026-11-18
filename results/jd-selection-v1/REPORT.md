# Judge on disagreement for the coding swarm (JD): +1 case

Plan `JD_SELECTION_PLAN.json` (frozen before any judge call). Same frozen 8 x 32K candidates and CX v2 output groups. In the 13 cases where feedback-passing programs split into groups with different outputs, a tournament starts from the group of the first feedback-passing agent; each other group challenges it on up to 3 inputs where they differ; a Nemotron thinking judge sees the public spec, examples, the input and the two outputs (random order) and says which one the spec requires. A challenger needs a strict majority. Infrastructure faults: 0.

| 72 cases, 8 agents | Solved |
|---|---:|
| first agent passing feedback | 56 |
| CX vote on generated inputs | 55 |
| **JD tournament** | **57** |
| oracle (any agent correct) | 64 |
| DeepSeek, 1 call | 61 |

The judge switched correctly in ledger s2 and common_free_slots s3, and wrongly in shell_words s2 (net +1). It said "neither" in most of the remaining disagreements, so the champion stayed. The remaining gap to the oracle is mostly cases where all feedback-passing programs agree on a wrong behaviour or the one correct program is outvoted before any disagreement is shown.

Reading: a concrete-output judge is a small, safe gain (it rarely overturns the default), much weaker than the arithmetic plan judge. Coding remains the one task family where the Nemotron swarm stays below DeepSeek (57 vs 61).
