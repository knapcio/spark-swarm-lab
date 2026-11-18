# bugbench evaluation: Nemotron with the whole project in context (L1F, L8F)

Context-gap experiment. Frozen plan `bugbench/LONG_CONTEXT_EVAL_PLAN.json` (frozen before any L-policy call on the 18 evaluation cases; development pilots v1-v4 on the 9 development cases only). Serving: Nemotron replicas restarted as `swarm-lightning-128k` clones (`ctx_switch.py`; same image and vLLM arguments except `--max-model-len 131072`). Prompt = exactly DeepSeek policy R's prompt (whole agent-visible bundle, ~15-20K tokens). Budget-forced calls, 32,768 completion tokens per call (= DeepSeek R `max_tokens`).

- **L1F**: one whole-bundle call; if the answer has a diagnosis but no FILE blocks, one format follow-up asking for FILE blocks only; public self-check; one repair on failure. FILE-marker normalization (glued/unterminated headers, END FILE with a path).
- **L8F**: 8 independent L1F agents; selection valid -> passes the project's public tests -> largest cluster of identical normalized diffs -> earliest. No model arbiter; hidden probes are graded once after the selection is frozen.

| Policy (same 18 cases x 2 seeds) | Fixed / 36 | wrong patch selected | no patch | mean calls | mean completion tokens |
|---|---:|---:|---:|---:|---:|
| DeepSeek R (whole repo, 1 call) | 36 | 0 | 0 | 1.0 | 2,786 |
| **Nemotron L8F (whole repo, 8 agents)** | **35** | 1 | 0 | 13.4 | 186,319 |
| Nemotron L1F (whole repo, 1 agent) | 26 | 6 | 4 | 1.5 | 20,764 |
| Nemotron 16K V3 (8 navigators + reviewer) | 28 | | | 38.3 | 122,233 |
| Nemotron 16K S1 (single navigator) | 18 | | | 4.8 | 15,888 |

Paired: L8F vs DeepSeek +0 / -1; L8F vs 16K V3 +8 / -1; L1F vs 16K V3 +4 / -6.
Oracle (any candidate passes the hidden grade): L8F 35/36, L1F 26/36, so the public-test selection lost nothing.

Run history: the eval ran as v1 + continuations v1b/v1c after admission halted on transport faults; the cause was my own overload (summed client concurrency above vLLM's max-num-seqs 25 on every node, queued requests hit the 120 s idle timeout; vLLM logs show Running 25 / Waiting 2-4). Merge rule frozen in the plan amendment: the earliest completed record per attempt; records used: L1F {'eval18-long-v1': 26, 'eval18-long-v1b': 7, 'eval18-long-v1c': 3}, L8F {'eval18-long-v1': 23, 'eval18-long-v1b': 8, 'eval18-long-v1c': 5}.

Reading: with the whole project in context, an arbiter-free swarm of 8 Nemotron agents fixes 35/36 planted bugs, essentially DeepSeek's 36/36, up from 28/36 for the best 16K swarm. The single whole-repo agent (26/36) is already as good as the 16K swarms. The cost is tokens: ~67x DeepSeek's completion tokens per case. The 16K bugbench gap was mostly a context gap.
