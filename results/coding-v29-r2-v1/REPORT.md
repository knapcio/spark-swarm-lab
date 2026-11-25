# Coding swarm R2 on the v2.9 single-Spark recipe (coding-v29-r2-v1)

Plan `CODING_V29_R2_PLAN.json` (18a8abb), frozen before any call: the coding-roll3-v1 R2 arm (same 72 cases of coding-hard-v1,
seeds 19-21, agent seed offset 6700, failure-driven replacement with 2 in flight, early stop, same worker and prompts) with only
the serving changed: Inkling-2-Mini-1x-DGX-Spark v2.9 (67e7be6) release defaults on each Spark (DFlash2 drafter
incoai/Inkling-2-Mini-DFlash2@4f9088ea, MEM_FRACTION 0.88, CTX 262144, target revision ed40e7da) behind the unchanged swarm shim.

| System | Solved /72 | Wrong | No answer | Tokens/case | Wall | GPU Wh | Wh per solved |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Swarm R2, v2.9 recipe serving** | **68** | 2 | 2 | 25,200 | 2,826 s | 71.1 | **1.04** |
| Swarm R2, stock cookbook serving (coding-roll3-v1) | 67 | 4 | 1 | 29,250 | 3,542 s | 89.2 | 1.33 |
| One DeepSeek V4.1 TP4 (deepseek-coding3-v1) | 57 | 0 | 15 | 12,498 (client) | 4,423 s | 150.3 | 2.64 |

Paired v2.9 vs stock R2 on the same 72 cases: v2.9-only 3, stock-only 2 (p = 1): accuracy equal within noise.
v2.9 serving: -20 % arm wall, -20 % GPU Wh, -14 % tokens per case (server counters; fewer cancelled tokens because agents
finish faster), Wh per solved 1.05 vs 1.33. Per-node decode tok/s while busy (60 s samples, median / max): Spark_01 130 / 491,
Spark_02 151 / 504, Spark_03 224 / 465, Spark_04 182 / 474. Lowest MemAvailable in the recipe memguard window (first 1,200 s):
3.95-4.77 GiB (floor 3.5); 5.7-6.7 GiB at the end. GPU rail energy only (nvidia-smi), a lower bound on wall-socket energy.
