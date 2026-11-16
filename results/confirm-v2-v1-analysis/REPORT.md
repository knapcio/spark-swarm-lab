# Fresh confirmation on arithmetic-v2 (48 new tasks x 3 seeds)

Fresh tasks generated after the protocol was frozen; every success is a plan accepted by the exact verifier. No CPU search, teacher, gold answers or communication between agents.

**Primary (paired, 144 cases):** swarm of 8 forced_explicit agents **144/144** (95% task-cluster interval 100.0%–100.0%) vs baseline 4 plain_original agents **93/144** (56.9%–72.2%); paired difference interval +27.8% to +43.1%.

Budget-matched (4 agents each, same 32,768-token ceiling): swarm 142/144 vs baseline 93/144.

| Agent type | Single-agent success | Mean completion tokens |
|---|---:|---:|
| plain_original | 155/576 (26.9%) | 7377 |
| forced_explicit | 985/1152 (85.5%) | 4905 |

| k | Baseline any-of-k (fixed / expected) | Swarm any-of-k (fixed / expected) |
|---:|---:|---:|
| 1 | 29 / 38.75 | 123 / 123.12 |
| 2 | 65 / 64.17 | 136 / 136.25 |
| 3 | 81 / 81.0 | 141 / 139.75 |
| 4 | 93 / 93.0 | 142 / 141.41 |
| 5 | — | 143 / 142.41 |
| 6 | — | 143 / 143.11 |
| 7 | — | 144 / 143.62 |
| 8 | — | 144 / 144.0 |

Swarm-unsolved cases: none. Deadlines 0, infrastructure failures 0, run errors []. Batch wall 4531 s (both arms interleaved; not per-arm throughput).
