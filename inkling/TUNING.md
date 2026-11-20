# Inkling-2-Mini on DGX Spark: serving recipe and tuning record (2026-11-20)

Model: `thinkingmachines/Inkling-2-Mini`, revision `6e7c8248f75265bdd4fbab5273304243b5d8c2cb` (26.4B total,
3.4B active MoE, 24 stored layers with the middle 12 run three times = 48 layer applications per token,
native NVFP4 experts + MXFP8 last four layers, 20.2 GB; bundled DSpark draft head `mtp.safetensors`).

## Recipe chosen

[`serve.sh`](serve.sh): SGLang `lmsysorg/sglang:inkling-2-mini` (arm64 digest
`sha256:bc811ac7ac68…`, sglang `0.0.0.dev1+g03fde9cc3.d20261120`), exactly the SGLang cookbook cell
`dgx-spark / nvfp4 / dspark` (TP1/EP1, `fa4`, BF16, page 128, `--speculative-algorithm DSPARK
--speculative-num-draft-tokens 8`, the four `SGLANG_OPT_*` DSpark/verify env flags, reasoning parser `inkling`,
tool parser `inkling2`), with three deviations: text-only (no `--enable-multimodal`), `--context-length 131072`,
and `--mem-fraction-static 0.62` instead of 0.45 (KV pool 517,760 → 833,408 tokens, enough for 25 agents with
32K completions each; host keeps ~39 GB free). Loopback only; reached through the existing SSH tunnels.

At release time (2026-11-20 ~22:10 Europe/Warsaw) the vLLM recipe's image `vllm/vllm-openai:inkling-2-mini`
did not exist on Docker Hub (vLLM >= 0.35 nightly required), so vLLM was not tried.

## Measurements (one DGX Spark each, on-box, through the adapter)

Workload: synthetic arithmetic puzzles (seeded, not from any evaluation set), thinking on (effort `high`),
temperature 0.8, streamed raw completions; aggregate = completion tokens / full wall. c1: 3 requests × 2048
tokens; c8: 16 × 4096; c24: 48 × 4096. One run per cell ([bench_think.py](bench_think.py)).

| Arm | c1 tok/s | c8 tok/s | c24 tok/s | Note |
|---|---:|---:|---:|---|
| No speculative decoding | 37.4 | 110.2 | 221.7 | Spark_01 |
| **DSpark 8 (cookbook)** | **51.3** | **190.7** | **362.7** | Spark_03; chosen |
| DSpark 8 + `SGLANG_ENABLE_NV_MEGA_RUNTIME_OPTIMIZATION=1` | 52.7 | 202.2 | 358.8 | Spark_02; no gain at c24 |
| DSpark 8 + ragged verify `cap-accept` with a GB10 SPS table | 51.3 | 150.7 | (invalid) | Spark_04; c24 cut by my restart |

- DSpark block size is fixed by the trained head (gamma 7 → exactly 8 draft tokens); 4 or 6 are refused at startup.
- Mean acceptance 3–4 tokens per verify step.
- Profiled SPS cost table (DSpark verify step time vs batch tokens, `sglang.benchmark.dspark_sps_profiler`):
  bs1 51 ms, bs2 80, bs4 108, bs8 122, bs16 163, bs24 183, bs32 203, bs48 249 ms per step.
- Torch profile of one c1 DSpark step (~55 ms): NVFP4 grouped MoE GEMMs ~28 ms, BF16 dense projections
  (Triton GEMV, ~240 GB/s) ~12.6 ms, LM head ~3.7 ms, the rest ~10 ms. The step is dominated by weight reads;
  the looped core re-reads its weights three times. No lossless lever of size was found; FP8 attention
  projections would change the model and were not tried.
- Startup ~6 min cold (weights 118 s, CUDA graph capture ~3.5 min), ~4 min warm.

## Harness adapter

[`shim.py`](shim.py) runs next to each server (`swarm-inkling-shim`, same image, port 18096 = the existing
tunnel target) and gives the unchanged Swarm Lab harness its vLLM dialect: `/tokenize` with chat messages
(rendered by the checkpoint's own chat template), raw token-id `/v1/completions` with `return_token_ids`,
`</think>` as the end-of-thinking marker, `vllm:num_requests_*` metrics. Thinking on/off maps to
`reasoning_effort` `high`/`none` (template default is `high` = 0.9). The forcing suffix `\n</think>\n` maps to
Inkling's own `<|end_message|><|message_model|><|content_text|>`, so a budget-forced answer continues the same
token sequence in the model's native format. Prompt-length parity with SGLang's own chat path was checked
(42 = 42 tokens). Smoke checks: one 32K arithmetic agent on development task hard-v1 #0 solved it (13,665
tokens); one 32K coding agent on development task `dev-repeating_expansion` passed feedback and holdout.
