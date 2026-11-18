# Night 2026-11-17/18: the context gap

Question: how much of Nemotron's gap to DeepSeek comes from our 16K serving window rather than the model?
Method: the four Nemotron replicas were restarted as clones with `--max-model-len 131072` (same image and all other vLLM arguments; `ctx_switch.py`), every comparison frozen in a plan before its first call, DeepSeek used only as a measured reference.

| Task family | Nemotron at 16K | Nemotron with more context / thinking | DeepSeek | Report |
|---|---:|---:|---:|---|
| Fresh hard arithmetic (hard-v4, 48 tasks x 2 seeds, plans frozen before the corpus) | (hard-v3: 31/48) | **82/96** (4 agents x 32K, 0 wrong) | 85/96 | results/confirm-xl-hard4-v2 |
| same, hybrid (DeepSeek only when the swarm says "no answer") | | **88/96** with 14 DeepSeek calls | 85/96 with 96 calls | results/confirm-xl-hard4-v2 |
| Hard arithmetic hard-v3 (48) | 31 | 38 (32K), 38 (64K) | 39 | results/xl-hard3-seed1-v1 |
| Bug fixing in 18 small projects x 2 | 28 (best navigating swarm) | **35** (8 agents, whole repo in context; 4 agents also 35) | 36 | bugbench/results/eval18-analysis/LONG_CONTEXT.md |
| Hard coding (72) | 34 (4 agents) | 51 (4 x 32K), 56 (8 x 32K), 57 with a disagreement judge | 61 | results/coding-hard-xl-v1, results/jd-selection-v1 |

Findings:
1. Most of the gap was the window, not the model. With 32K of thinking (and the whole repository for bug fixing) an arbiter-free Nemotron swarm comes within noise of DeepSeek on fresh hard arithmetic (82 vs 85 of 96, sign test p = 0.51) and on bug fixing (35 vs 36), still with zero wrong answers on arithmetic.
2. 32K is the efficient point. 64K makes a single agent better (arithmetic 23 -> 29 of 48) but not the swarm, and does not help coding.
3. Coding is the remaining gap (57 vs 61), and it is a selection gap: some agent is right in 64/72 cases. Voting on self-generated inputs did not help (55); a Nemotron judge on concrete disagreeing outputs adds one case (57).
4. Cost: the swarm spends far more tokens than DeepSeek (about 15x on arithmetic, 30-70x on code and bug fixing). The hybrid keeps DeepSeek-level or better accuracy while calling DeepSeek on about 15% of tasks.
5. Operational lesson: summed client concurrency must stay at or below vLLM's max-num-seqs (25) per node; queued requests receive no byte and hit the 120 s idle timeout. Three runs needed documented continuations because of this.
