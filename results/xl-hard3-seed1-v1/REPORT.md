# XL: 32K thinking for deep Nemotron agents (arithmetic-hard-v3, seed 1)

Context-gap experiment. Plan `XL_HARD3_PLAN.json` (frozen before any call). Serving: the four Nemotron replicas restarted as `swarm-lightning-128k` clones (`ctx_switch.py`; same image and vLLM arguments except `--max-model-len 131072`). Agent `xl_forced_original` (source `research/xl-v1` 40b2bd5) = the deep agent with thinking cap 30720 and total 32768 (DeepSeek's `max_tokens`), instead of 14848/16000. Same 48 tasks and seed as the 16K board confirmation and the DeepSeek 32K baseline; same arbiter-free selection (Nemotron thinking judge, first accepted plan). Errors: []; agent deadlines hit: 0.

| Policy (48 cases) | Nemotron 16K | **Nemotron 32K** | paired 32K vs 16K | DeepSeek 32K alone | paired 32K vs DS | wrong answers (32K) | no answer (32K) | tokens/case 16K -> 32K |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| deep4 (4 identical deep agents) | 31 | **38** | +7 / -0 | 39 | +4 / -5 | 0 | 10 | 58,900 -> 90,649 |
| board2x2 (shared failure board) | 32 | **37** | +5 / -0 | 39 | +1 / -3 | 0 | 11 | 44,366 -> 66,559 |

Single agent (agent 0 of deep4, verifier-scored): 16K 19/48 -> 32K 23/48.
Hybrid with 32K deep4 (DeepSeek only where the swarm gave no answer): 43/48 with 10 DeepSeek calls (DeepSeek alone 39/48 with 48 calls).

Reading: doubling the thinking budget is the single biggest lever found so far on hard arithmetic. deep4 at 32K goes from 31 to 38/48 (paired 7-0), essentially DeepSeek's 39/48, still with zero wrong answers; it costs ~1.5x the tokens of the 16K swarm. The 16K gap to DeepSeek was mostly a thinking-budget gap, not a model gap. Exploratory size (48 cases, one seed); the paired 16K comparison is on identical cases.
