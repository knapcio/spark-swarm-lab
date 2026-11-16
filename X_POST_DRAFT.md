# X post draft — owner publishes

I spent the night testing small-agent swarms on 4 DGX Sparks: voting, shared state, self-repair, independent search, evolution and rejected candidates reused as reviewers.

The useful finding: changing what the agents produce mattered more than simply adding agents.

On 24 arithmetic tasks × 3 seeds, Nemotron 3.5 Lightning scored:

- One reasoning call: 18/72
- Sequential self-repair: 45/72
- Four independent full plans (any verifier-passing one accepted): 49/72
- 32-agent stepwise democracy, thinking off: 15/72

Democracy used a different thinking/budget recipe, so this is not a voting-only ablation. The four-plan advantage over strong sequential repair was uncertain (+5.6 pp, task-cluster 95% interval −5.6 to +16.7), and it cost more tokens. More agents were not automatically better.

Direct graph assignments failed in our tested recipes. Asking the same small model to write a reusable solver was much more effective: independent program search reached 376/384 outcomes on 96 additional graphs. Three selected programs each solved all 96.

Reusing bottom-ranked contexts as reviewers matched that total; we have no evidence yet that review itself improved it. Only four training seeds per method: promising, still exploratory.

For context, our pinned native DeepSeek TP4 reference solved all 126 original math/coding attempts. Different model, serving recipe and compute budget; not an equal-cost ranking.

Code, protocols, plots, real proposal/review trees and evidence:
https://github.com/knapcio/spark-swarm-lab

Suggested figures: arithmetic confidence intervals; additional-graph confirmation; real reviewer lineage. Full article draft: ARTICLE_DRAFT.md. Evidence release: https://github.com/knapcio/spark-swarm-lab/releases/tag/study-20261116
