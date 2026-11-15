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

## Reliability incident and an isolated v0.32 canary candidate

2026-11-15, Europe/Warsaw — research update after Spark_02's engine failed
after approximately 3.4 hours on the pinned v0.27.1/DSpark3 recipe. The saved
`spark02-engine-failure-1636.log` reports illegal CUDA memory access while
`mamba2_attn.py` reads `torch.any(common.has_initial_states_p).item()`.
This is a synchronization point; the originating kernel and cause remain
**unknown**. The failed scheduler step had 25 new 134-token prompts, zero
prefix-cache hits and 8.67% KV-cache utilization. These facts do not establish
an OOM or a prefix-resume fault.

The most specific source-level lead is upstream
[issue 55600](https://github.com/vllm-project/vllm/issues/55600) and
[fix 55601](https://github.com/vllm-project/vllm/pull/55601), merged October 7 as
[`3d6853b32c7c872df00d9e3489f642dc22e974e0`](https://github.com/vllm-project/vllm/commit/3d6853b32c7c872df00d9e3489f642dc22e974e0).
With heterogeneous cache-group block sizes, the V2 runner can seed a restored
Mamba-state column in attention-block units, causing an out-of-bounds read or
wrong recurrent state. The fix uses `mamba_block_size`. Its reported reproducer
used GLM/DFlash2 on GB10; **our failure has not been linked to that mechanism**.

Source inspection found the old divisor in stable v0.28.0, v0.29.0, v0.30.0
and v0.31.0; [v0.32.0 contains the fix](https://github.com/vllm-project/vllm/blob/v0.32.0/vllm/v1/worker/gpu/model_states/mamba_hybrid.py).
The official registry's v0.31 tag listing contains only v0.31.0 variants, not a
stable v0.31.1. Thus **v0.32.0 is the earliest verified stable release candidate
in this check**, preferable to a larger blind jump to v0.33.0.

Read-only registry manifest/config inspection verified this candidate:

```text
vllm/vllm-openai:v0.32.0
linux/arm64 child: sha256:6ff5ff0ddf3658d2c2d677dac5ca2d4726ce0156b4371166d918181b210bd4bc
multiarch index:   sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34
config:           sha256:4ceb6c60eed291c1d179c35674bd8ece7acfd4f9abe8b9be83a6a4dcc3c70ea2
image source:     5df63a7203cdb9328d824a27b682e77c7b9928be
image CUDA:       13.0.2
```

Primary artifact metadata: [Docker Hub tag](https://hub.docker.com/v2/repositories/vllm/vllm-openai/tags/v0.32.0/)
and [official release](https://github.com/vllm-project/vllm/releases/tag/v0.32.0).
The inspected image configuration, rather than the source Dockerfile's current
default build argument, supplies the CUDA version above. Existing driver
580.173.02 exceeds the [CUDA 13.0 Update 2 requirement of 580.95.05](https://docs.nvidia.com/cuda/archive/13.0.2/cuda-toolkit-release-notes/).
No driver change is indicated by that requirement. This is compatibility
evidence, not a successful GB10 deployment or reliability qualification.

Static [argument documentation](https://docs.vllm.ai/en/v0.32.0/configuration/engine_args/)
and source retain DSpark, the pinned draft's `Qwen3DSparkModel` architecture,
FlashInfer Mamba, `align` caching, [Marlin NVFP4](https://docs.vllm.ai/en/v0.32.0/features/quantization/modelopt/),
and the `nemotron_v3` / `qwen3_coder` parsers. Cache mode `all` was removed;
our explicit `align` remains accepted. Source dependency pins are PyTorch
2.13.0 and FlashInfer 0.7.0.post1; v0.33.0 instead pins 2.14.0 and 0.7.2.post1.
Preserving flags does not preserve every engine default or numerical path.

The proposed next comparison is a **separate Spark_02 canary**, with the same
target/draft snapshots and explicit settings, changing only the image and
using a separate loopback port/container. Retain the old container for rollback.
First reproduce the failed sequence on the unchanged recipe; then qualify the
candidate with functional/tool checks, the same short throughput workload,
mixed concurrent requests and cancellation/drain transitions. A short passing
smoke cannot establish reliability against a fault observed only after hours.
Record request count, elapsed exposure and every failure; keep old/new runtime
cohorts separate and rerun the complete comparison if adopting a new recipe.

Diagnostic alternatives, each tested separately if needed:

- `--enforce-eager`: removes CUDA graphs. An [exact-model SM110 report](https://github.com/vllm-project/vllm/issues/55406)
  found it effective on v0.28.0; different hardware and failure sequence mean
  it is a candidate workaround, not proof for this GB10 incident.
- `--no-enable-prefix-caching --mamba-cache-mode none`: removes the align
  cache-resume path. This changes caching and cost; no demonstrated fix here.
- `CUDA_LAUNCH_BLOCKING=1`: debug synchronous fault reporting, not a performance
  recipe; synchronization can mask races.

The often-cited [accepted-token-copy race](https://github.com/vllm-project/vllm/pull/53919)
is marked V1-runner-only; DSpark uses V2. Historical FlashInfer CUTLASS MoE
reports also do not directly explain our explicitly Marlin MoE route. Neither
is sufficient reason to change backend, precision, driver or algorithms.

Evidence receipt: `diagnostics/swarm-prototype-20261115/vllm032-canary-research.json`
in the parent infrastructure workspace. This research pulled no image layers,
made no model inference/SSH calls, and changed no serving or fleet source.
