# Coding-hard with a 32K thinking budget (code_xl)

Context-gap experiment. Plan `CODING_HARD_XL_PLAN.json` (frozen before any call; amendment_1 = continuation after a 2-minute SSH-tunnel stall, v1 225 agents + v1b 65 agents, faulted agents rerun). Serving: `swarm-lightning-128k` clones (only `--max-model-len` differs). Agent `code_xl` (source `research/coding-xl-v1` a41c312) = the deep coding agent with thinking cap 30720 / total 32768 (DeepSeek's `max_tokens`) instead of 14848 / 16000. Same 24 evaluation tasks x 3 seeds, same sandbox and grading, same arbiter-free selection: the first agent (fixed order) whose code passes all public feedback cases; solved if that code passes all hidden holdout cases.

| 72 cases | Nemotron 16K | **Nemotron 32K** | DeepSeek 32K (1 call) |
|---|---:|---:|---:|
| single agent (agent 0) | 22 | **37** | 61 |
| 4 agents, first passing feedback | 34 | **51** | |

Paired 4-agent swarm 32K vs 16K: +21 / -4. 32K swarm vs DeepSeek: +5 / -15.
Arbiter-free behaviour of the 32K swarm: it answered (some agent passed the public feedback cases) on 60/72 cases; 9 of those answers failed the hidden holdout (wrong); 12 cases had no feedback-passing code.
Hybrid (DeepSeek only where no agent passed feedback): 57/72 with 12 DeepSeek calls (DeepSeek alone 61/72 with 72 calls).
Oracle (any of the 4 agents passes holdout): 59/72. Mean agent completion tokens per case: 16K 57,259 -> 32K 88,024.

Reading: doubling the thinking budget lifts a single Nemotron coding agent from 22 to 37/72 and the 4-agent swarm from 34 to 51/72, closing more than half of the gap to DeepSeek (61/72). As in arithmetic, the 16K budget, not only the model, was holding Nemotron back.
