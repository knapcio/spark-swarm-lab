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

## Day 2026-11-21: cancel the other agents once one plan is accepted ([swarm-cancel-hard6-v1](swarm-cancel-hard6-v1/REPORT.md))

Frozen plan (2376372) before a fresh corpus (arithmetic-hard-v6, d8bc18e); three arms run alone on the fleet, 96 paired
cases each, server-side token counting (includes aborted requests), GPU-rail energy.

| Arm | Solved | Wrong | Server tokens/case | Arm wall | GPU energy per solved case |
|---|---:|---:|---:|---:|---:|
| A deep4 (all 4 agents to the end) | 86 | 0 | 66.3K | 87 min | 1.92 Wh |
| **B deep4cancel** (first accepted plan ends the case) | 83 | 0 | **44.6K (-33 %)** | **56 min (-36 %)** | **1.30 Wh** |
| C waves of 2 with cancel | 81 | 0 | 39.3K (-41 %) | 59 min (-32 %) | 1.32 Wh |

B missed the frozen non-inferiority margin (>= 84) by one case, but every one of its 4 losses was a case where it
cancelled nothing (it ran A's policy and drew worse samples); where it cancelled, the answer was already accepted by a
judge with 0 false accepts. Same-seed agents changed outcome in 18 % of pairs between the two runs, so a 3-case gap
between identical policies is ordinary. **deep4cancel is now the default arithmetic swarm policy** (owner decision).
The shim now treats client disconnects as cancellations (`shim:client_cancels`; SGLang aborts in < 0.5 s).
Offline, the same early stop on the coding swarm would keep 69/72 (not the disproof 70) for about a third fewer tokens.
[One DeepSeek on the same hard-v6 tasks](swarm-cancel-hard6-v1/DEEPSEEK.md): 85/96 (swarm A 86, paired +3/-2) at 1.29 Wh per
solved case, the same as swarm B (1.30). Exploratory pooled v4+v5+v6 (288): swarm 254 vs DeepSeek 246 (+17/-9, p = 0.17).

## Incidents

- Coding source a41c312 still had a 1800 s per-request wall limit; Inkling at ~18 tok/s per request under 25-request load
  needs ~30 min for 32K tokens. Six agents hit it; the runner stopped admissions as designed; fixed in c2eb89e (14400 s),
  plan amendment 1, faulted and unstarted agents rerun (v1b).
- One tuning measurement (ragged verify at 24 requests) was invalidated by my own restart; reported as invalid.

## Reports

[inkling-hard4-v1](inkling-hard4-v1/REPORT.md) · [inkling-coding-hard-v1](inkling-coding-hard-v1/REPORT.md) ·
[inkling-bugbench-long-v1](inkling-bugbench-long-v1/REPORT.md) · [disproof-selection-v1](disproof-selection-v1/REPORT.md) ·
[efficiency-v1](efficiency-v1/REPORT.md) · [inkling-hard5-v1](inkling-hard5-v1/REPORT.md) ·
[swarm-cancel-hard6-v1](swarm-cancel-hard6-v1/REPORT.md)
