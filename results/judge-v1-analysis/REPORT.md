# Nemotron as its own judge (arbiter-free selection)

Candidates: every parsed plan of the 8 budget-forced agents per case in confirm-v2-v1 (1,142 plans) and confirm-hard-v1 (1,140 plans). The judge (same Nemotron checkpoint) saw only the public task and the candidate's raw JSON plan; the exact verifier's verdict was used only to score the judge afterwards.

| Judge mode | Corpus | Judged | True accept | False accept | True reject | False reject | Unparsed | Accuracy |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| fast (thinking off, 512 tokens) | v2 | 1,142 | 244 | 33 | 124 | 741 | 0 | 32.2% |
| fast | hard | 1,140 | 51 | 175 | 742 | 172 | 0 | 69.6% |
| think (budget-forced, 6,144 + continuation) | v2 | 1,142 | 979 | **0** | 157 | 6 | 0 | 99.5% |
| think | hard | 1,140 | 223 | **0** | 912 | 0 | 5 | 99.6% |

Arbiter-free swarm: in each case, take agents in their fixed order and select the first plan the thinking judge accepts; score it with the verifier.

| Agents k | v2 oracle | v2 judge-selected | hard oracle | hard judge-selected | wrong selections |
|---:|---:|---:|---:|---:|---:|
| 1 | 123 | 121 | 35 | 35 | 0 |
| 2 | 136 | 136 | 46 | 46 | 0 |
| 4 | 142 | 142 | 64 | 64 | 0 |
| 8 | 144 | 144 | 81 | 81 | 0 |

With thinking, the model checks a given plan almost perfectly (no false accepts in 2,282 judgements), so for this task the swarm needs no external verifier: one of its own agents can be the verifier. Without thinking, the judge is unusable. Checking a plan is far easier than finding one; this need not transfer to code or bugs, where checking requires executing or reasoning about a program.
