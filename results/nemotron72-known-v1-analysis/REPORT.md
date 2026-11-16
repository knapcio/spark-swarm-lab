# Known72 follow-up: single agent and independent swarm

Exploratory: these 24 evaluation tasks (x3 seeds) were seen while designing the methods. Not fresh generalization. Every success is a plan that passed the exact verifier; no CPU search, teacher, gold answers or shared memory.

**Single scribe_full agent:** 51/72 (task-cluster 95% interval 58.3%–81.9%). Historical references on the same 72 attempts: one reasoning call 18/72, four independent reasoning plans 49/72, native DeepSeek 72/72.

## Independent swarm (8 agents per case)

All 8 agents: **69/72** (task-cluster 95% interval 87.5%–100.0%). Deadlines 0, infrastructure failures 0.

| Agents k | Solved (fixed order) | Expected over all k-subsets | Completion tokens |
|---:|---:|---:|---:|
| 1 | 55/72 | 54.0 | 469,135 |
| 2 | 61/72 | 63.8 | 877,882 |
| 3 | 67/72 | 66.9 | 1,381,011 |
| 4 | 68/72 | 68.1 | 1,764,105 |
| 5 | 69/72 | 68.7 | 2,254,320 |
| 6 | 69/72 | 68.9 | 2,646,687 |
| 7 | 69/72 | 69.0 | 3,135,692 |
| 8 | 69/72 | 69.0 | 3,522,868 |

| Agent type | Single-agent success | Mean completion tokens | Runs hitting a length cap | 4 agents of this type |
|---|---:|---:|---:|---:|
| scribe_full | 213/288 (74.0%) | 6776 | 179 | 67/72 |
| scribe_explicit | 219/288 (76.0%) | 5456 | 96 | 66/72 |

Hardest tasks (at most 2 of 8 agents in some seed): eva-e40959c347a7, eva-eea066d2b2d7, eva-f087ad404500.

## Budget-forced agents (forced_explicit)

Single-agent success 236/288 (81.9%); mean completion tokens 5169, mean prompt tokens 2906. Any of 4: 70/72.
