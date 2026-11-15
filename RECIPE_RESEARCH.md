# Nemotron Lightning on GB10: serving recipe research

Research date: 2026-11-15, Europe/Warsaw. Target: 25 active requests per GB10,
four independent replicas, 16K context. No SSH, image/model downloads, deployment,
or GPU measurements were performed for this note. `fleet.sh` was not changed.

## Decision

Keep the already selected, pinned **vLLM 0.27.1 target-only baseline** for the
first functioning prototype. **DSpark with three speculative tokens is the most
promising first performance comparison**, using the same image and target weights.
Published GB10 evidence supports DSpark at c8 and reports good c32 throughput,
but does not establish the winner at our c25/16K settings. Do not describe the
baseline, or DSpark, as a measured universal optimum.

No new runtime build, engine migration, driver update, long-context allocation,
or tuning framework is justified for this prototype.

## What was actually measured elsewhere

Evidence labels: A = official deployment support or registry/config inspection;
B = first-person GB10 measurement with a stated method; C = measurement with
missing exact runtime or provenance needed for reproduction. These are not
independent replications on our hardware.

| Source | GB10 result | What it establishes / limits |
|---|---|---|
| [DevelopersIO, Aug 12](https://dev.classmethod.jp/en/articles/nvidia-nemotron-3-5-lightning-dspark-dflash-mtp-dgx-spark/) — B | c8 aggregate output tok/s: target-only **241.67**, MTP **302.27**, DFlash **268.61**, DSpark **354.56**. c1 per-request: 81.27 / 111.36 / 95.48 / 124.24. | Stock vLLM0.27.1, four rotating code prompts, thinking off, two warmups. DSpark wins this matched c8 comparison by46.7%. Prompt reuse can still produce cache hits; this is not c25 evidence. |
| [Petronella, Oct 2 battery](https://petronellatech.com/ai/llm-benchmarks/models/nemotron-3-5-lightning/) — C | DSpark k3: **608 aggregate tok/s at c32**, **795.4 at c64**; prose c1 90.2. | Actual single-GB10 report, thinking off, vendor recipe. Runtime is only identified as vLLM nightly, with an internal source-file name rather than accessible raw runs or an image digest. Useful feasibility evidence, not an exact launch recipe. |
| [ASUS GX10 owner, HF discussion5](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4/discussions/5) — B with concurrency caveat | HumanEval c8: target198.9 / DFlash239.4 / DSpark317.7 output tok/s. ShareGPT c8:195.4 /204.4 /271.6. | Only ten prompts were submitted per point. The columns labelled c16/c32 were effectively **c10**, as explicitly corrected by the author; do not quote them as high-concurrency results. |
| [HP ZGX Nano MTP study, Aug 11](https://huggingface.co/blog/curtburk/nemotron-35-lightning-bnchmrk) — B | True c16 baseline81.1 / MTPk3 128.6 aggregate output tok/s; c32 94.7 /153.9. | HP Z Runtime0.29 wrapping vLLM0.24; structured corpus, temperature0. Supports possible MTP gains under load, but its absolute speeds and stack differ substantially. Not a reason to replace our runtime. |
| [styles01 Spark Arena runbook](https://github.com/styles01/sparkrun-recipes/blob/main/runbooks/nemotron-3.5-lightning-30b-a3b-nvfp4.md) — B/C | vLLM0.27.1 DSpark4, c10:224.4 generation tok/s at depth0,85.1 at16K. | pp2048/tg128, three runs; limit10, utilization0.60. No c25 test or matched DSpark3/4 raw crossover. Many extra environment settings are bundled together; do not import the bundle into this prototype. |
| [sojufx GB10 recipe/results](https://github.com/sojufx/Nemotron-3.5-Lightning-30B-A3B-NVFP4-DGX-Spark-Recipe/blob/main/results/1m-vllm0271-dspark-k3.md) — B/C | DSpark3 c4:198.2 agent/tool,265.0 code-edit aggregate tok/s. | Max context1M, output256, temperature0, one repeat. Configured1M is not proof every benchmark prompt contained1M tokens. Low concurrency only. |

[Mia's SGLang recipe](https://github.com/MiaAI-Lab/Nemotron3.5-Lightning-DGX-Spark-RTX-5090-6000-PRO)
publishes a working dev-container configuration and a48-request capacity report,
not a measured c25 output-throughput win. Its `dev-nemotron3-5-lightning` tag,
float16 SSM cache and graph settings introduce additional variables. Keep it as
an alternative, without changing the current engine on capacity figures alone.

## Exact baseline retained

Registry inspection confirmed `linux/arm64`, CUDA13.0.2, and entrypoint
`["vllm", "serve"]` for the official image:

```text
vllm/vllm-openai@sha256:1c8e60a0841b333c700488cb029d3664807249da0c071e862191b00fe34b228c
```

This is the ARM64 child manifest for tag `v0.27.1`; multi-platform tag digest:
`sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967`.

Target: `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, revision
`bee7596271d1495f6992ae224aefde4410e816b8` (52 shards,21,561,882,284 bytes).

Arguments after the image entrypoint:

```bash
/model --served-model-name nemotron-lightning \
  --host 127.0.0.1 --port 18096 \
  --max-model-len 16384 --max-num-seqs 25 \
  --max-num-batched-tokens 4096 --gpu-memory-utilization 0.70 \
  --moe-backend marlin --kv-cache-dtype fp8 \
  --mamba-backend flashinfer --mamba-cache-mode align \
  --enable-prefix-caching --enable-chunked-prefill \
  --reasoning-parser nemotron_v3 \
  --tool-call-parser qwen3_coder --enable-auto-tool-choice
```

The backend/parser combination and target-only route are documented in the
[NVIDIA cookbook](https://github.com/NVIDIA-NeMo/Nemotron/blob/main/usage-cookbook/Nemotron-3.5-Lightning/vllm_cookbook.ipynb).
Our c25/16K/0.70/4096 values are conservative prototype choices, not vendor speed
claims. Retain default FP32 SSM cache initially.

## Only two follow-up candidates

After one stable baseline measurement at c25, keep all other settings fixed:

1. **DSpark3:** add a read-only `/draft` mount containing
   `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark` at revision
   `6d127b50ecd98562cea85d0087680b7d86091fb0` (1,349,057,504 weight bytes), plus:

   ```bash
   --speculative-config '{"method":"dspark","model":"/draft","num_speculative_tokens":3}'
   ```

2. **MTP1**, if avoiding another model download is preferable, or DSpark loses:

   ```bash
   --speculative-config '{"method":"mtp","num_speculative_tokens":1,"moe_backend":"flashinfer_cutlass"}'
   ```

These are alternative launches. Do not stack them. The MTP drafter backend is
separate from the target's Marlin backend. The official GB10 cookbook uses MTP1;
do not copy a longer datacenter MTP configuration and assume the same result.
No tuning flags above have been applied by this research task.

## Compatibility and correctness checks

- [CUDA13.0.2 release notes](https://docs.nvidia.com/cuda/archive/13.0.2/cuda-toolkit-release-notes/)
  list R580 compatibility and bundled Linux driver580.95.05. Requested host
  driver580.173 exceeds that; no driver upgrade is indicated by this requirement.
  This is a compatibility inference, not a successful GPU smoke on our nodes.
- Keep `chat_template.jinja` with the target snapshot. vLLM parser is
  `nemotron_v3`; SGLang and TensorRT use different spellings.
- For finite fast worker calls use `chat_template_kwargs.enable_thinking=false`,
  temperature1.0/top_p0.95 and an explicit output limit. Test a real tool round
  trip, not merely JSON-looking prose. If reasoning is enabled, NVIDIA's cookbook
  advises `force_nonempty_content=true` for coding-agent tool calls.
- Compare **completion tokens / full wall time** on the same diverse prompts,
  plus TTFT and successful tool calls; warm the engine first. Include at least
  100 requests for c25 so the client can actually sustain the requested load.
- Four replicas multiply capacity only approximately. No cited result measures
  our four-node100-active-request system. Cached capacity estimates and a
  configured context ceiling are not measured concurrency throughput.

Unresolved: target-only versus DSpark/MTP at c25 with our16K histories and
sampling; cache-hit distribution; long-run error rate; tool-task success;
whether a second small flag change improves useful throughput. Resolve only
what is needed after the simple baseline works.
