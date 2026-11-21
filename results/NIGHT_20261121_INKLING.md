# Night 2026-11-20/21: Inkling-2-Mini replaces Nemotron in the Swarm Lab

Thinking Machines released Inkling-2-Mini on 2026-11-20 (26.4B total / 3.4B active MoE, the middle 12 of 24 layers
looped three times, native NVFP4 + MXFP8, bundled DSpark draft head). This night: a fast serving recipe for one DGX
Spark, the unchanged Swarm Lab harness pointed at it, and the main experiments rerun with frozen plans.

## Serving ([inkling/TUNING.md](../inkling/TUNING.md))

SGLang `lmsysorg/sglang:inkling-2-mini` with the cookbook DGX Spark DSpark recipe (8 draft tokens), text-only,
128K context, `--mem-fraction-static 0.62`. Per Spark: 51 / 191 / 363 tok/s at 1 / 8 / 24 concurrent thinking requests
(no speculative decoding: 37 / 110 / 222). Two further levers (NV mega-runtime flag, ragged verify with a profiled GB10
cost table) gave nothing. A torch profile shows the step is dominated by weight reads, with the looped core read three
times. A small adapter ([inkling/shim.py](../inkling/shim.py)) gives the harness its vLLM dialect, so no harness code changed.

## Results (same tasks, seeds, budgets, harness and selection rules as the Nemotron runs)

| Task family | One DeepSeek V4.1 | One Nemotron | Nemotron swarm | **One Inkling** | **Inkling swarm** |
|---|---:|---:|---:|---:|---:|
| Hard arithmetic, 96 cases (4 agents + own judge) | 85 | 54 | 82 | 69 | **90** (0 wrong) |
| Hard arithmetic, fresh hard-v5, 96 cases | 76 | | | 61 | **78** (0 wrong) |
| Hard coding, 72 cases (8 agents) | 61 | 37 | 56 | **62** | **69** |
| Bug fixing, whole project in context, 36 | 36 | 26 | 35 | **36** | 36 |

- [Fresh replication](inkling-hard5-v1/REPORT.md) on arithmetic-hard-v5 (plans frozen before the corpus existed): swarm 78 vs DeepSeek 76 (+8/-6).
  Pre-registered pooled test over 192 cases: 168 vs 161, +14/-7 (p = 0.19), 0 wrong; One Inkling 130 is clearly below DeepSeek (p = 3e-6).
  So the swarm matches DeepSeek, it does not beat it significantly.
- Arithmetic hard-v4 swarm vs DeepSeek paired +6/-1 (p = 0.125); vs Nemotron swarm +9/-1 (p = 0.02). Judge: 0 false accepts in 330.
- Coding swarm vs DeepSeek +10/-2 (p = 0.039); One Inkling vs DeepSeek +8/-6 (p = 0.79).
- [Executable disproofs](disproof-selection-v1/REPORT.md) (astra idea #1): contracts written from the public task alone
  are the best arbiter-free code selector so far: Nemotron candidates 56 -> 59 (judge 57, output vote 55; oracle 64),
  Inkling candidates 69 -> 70 (oracle 71).

## Does it pay now? ([efficiency-v1](efficiency-v1/REPORT.md), Fable idea #6)

Same four Sparks, GPU-rail energy from 1 Hz `nvidia-smi`: the Inkling fleet (four replicas) produces 1,412 tok/s at
0.083 J/token; DeepSeek TP4 at its 16 slots 276 tok/s at 0.44 J/token. Per solved task, One Inkling solves ~5x more coding
tasks per hour than One DeepSeek at ~1/5 of the GPU energy (equal accuracy), and is cheaper on bugs and arithmetic too.
The Inkling swarm is the most accurate system and costs more energy per solved task than One DeepSeek.

## Incidents

- Coding source a41c312 still had a 1800 s per-request wall limit; Inkling at ~18 tok/s per request under 25-request load
  needs ~30 min for 32K tokens. Six agents hit it; the runner stopped admissions as designed; fixed in c2eb89e (14400 s),
  plan amendment 1, faulted and unstarted agents rerun (v1b).
- One tuning measurement (ragged verify at 24 requests) was invalidated by my own restart; reported as invalid.

## Reports

[inkling-hard4-v1](inkling-hard4-v1/REPORT.md) · [inkling-coding-hard-v1](inkling-coding-hard-v1/REPORT.md) ·
[inkling-bugbench-long-v1](inkling-bugbench-long-v1/REPORT.md) · [disproof-selection-v1](disproof-selection-v1/REPORT.md) ·
[efficiency-v1](efficiency-v1/REPORT.md) · [inkling-hard5-v1](inkling-hard5-v1/REPORT.md)
