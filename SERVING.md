# Serving qualification — v0.32.0 canary and historical v0.27.1 results

## Completed runtime-v2 four-replica qualification

On **2026-11-15 at 16:46:18 UTC (17:46:18 Europe/Warsaw)**, all four replicas passed the [health/idle gate](results/runtime-v2-fleet-qualification/health-receipt.json). [Container inspection](results/runtime-v2-fleet-qualification/serving-inspection.json) records the same pinned v0.32.0 ARM64 image and serving command on every node, running with restart count 0 and OOM false. This is dated readiness evidence, not a promise of sustained crash-free operation.

One concurrent mixed fleet batch completed **416 requests, including 16 warmups**, with **69,158 completion tokens / 39.008007 full wall seconds = 1,772.918 output tok/s**, and zero recorded transport errors. The full wall includes warmups and drain; a metrics monitor polled every **0.2 seconds**. Each endpoint reached an observed peak of **25 running requests**, matching its engine cap. Endpoint peaks are sampled observations rather than proof that all 100 slots remain active throughout the batch. [Full-wall aggregate](results/runtime-v2-fleet-qualification/mixed-fleet-summary.json).

| Replica | Measured requests + warmups | Warmed output tok/s | Measured wall s | Exact JSON checks | Length finishes / 100 |
|---|---:|---:|---:|---:|---:|
| [Spark01](results/runtime-v2-fleet-qualification/mixed-1.json) | 100 + 4 | 540.80 | 30.564 | 13/37 | 62 |
| [Spark02](results/runtime-v2-fleet-qualification/mixed-2.json) | 100 + 4 | 542.49 | 30.438 | 13/37 | 63 |
| [Spark03](results/runtime-v2-fleet-qualification/mixed-3.json) | 100 + 4 | 551.42 | 29.901 | 13/37 | 63 |
| [Spark04](results/runtime-v2-fleet-qualification/mixed-4.json) | 100 + 4 | 539.28 | 30.635 | 13/37 | 63 |

The per-node table excludes warmups from measured wall; its rates are not added to obtain fleet throughput. All nodes use the finite mixed100/c25/T0/thinking-OFF/256-token-cap workload. Long answers can be truncated; the three constrained JSON task types are a limited correctness check. This single diagnostic batch supports neither an agent-method ranking nor a causal speed/scaling comparison with historical serving measurements, and it is not a sustained decode-only rate.

Separate four-endpoint short-JSON probes passed **100/100 at T0 and 100/100 at T0.8**, with 25 clients per distinct endpoint: [T0](results/runtime-v2-fleet-qualification/short100-t0.json), [T0.8](results/runtime-v2-fleet-qualification/short100-t0.8.json). Real `add(17,25)` tool round trips passed on [Spark01](results/runtime-v2-fleet-qualification/tool-1.json), [Spark02](results/runtime-v2-fleet-qualification/tool-2.json), [Spark03](results/runtime-v2-fleet-qualification/tool-3.json) and [Spark04](results/runtime-v2-fleet-qualification/tool-4.json). These interface probes are separate from the 416-request timed batch.

The [manifest](results/runtime-v2-fleet-qualification/manifest.json) covers **13 byte-identical original reports**. The [independent qualification audit](results/runtime-v2-fleet-qualification/qualification-audit.json) reconciles all measured/warmup token totals and wall denominators, four image/command pins, health/idle states, probe responses and tool arguments/results. No model API was called during curation. The amended runtime-v2 primary study started after this gate; its task-quality reports remain separate.

## v0.32.0 single-node qualification — 2026-11-15

The earlier **Spark_02 canary** qualified for the next uniform runtime-v2 study: the old and new recipes each completed 20 bounded diagnostic replays, and v0.32.0 passed two short-JSON probes, a real tool round trip and one reasoning-on exact-plan smoke. Four-node readiness was pending at that canary stage and is recorded separately above. This evidence does not certify sustained crash-free operation or identify the earlier CUDA crash's root cause.

The [runtime-v2 amendment](RUNTIME_V2_AMENDMENT.json) selects v0.32.0 with upstream hybrid-state indexing fixes after the v0.27.1 serving failure. Model and draft weights/revisions, agent policies, prompts, tasks, budgets and serving flags stay fixed. The image change also changes dependency/kernel implementations and uses a separate compilation cache. All **900 primary cases plus 80 supplementary solo attempts will run fresh** under v2, without pooling the old first-seed arithmetic rows. Prior outcomes had already been inspected; the amendment records that exposure explicitly.

### Matched c25 throughput comparison

Three old-image repeats preceded three new-image repeats on the same Spark. Each sends 100 mixed requests, 25 workers, temperature 0, thinking OFF and a 256-token cap, with four untimed warmups. Throughput is completion tokens divided by full measured batch wall, including prefill/scheduling/HTTP; warmups are excluded. Prefix caching remains enabled. This is separate from the historical target-only versus DSpark comparison below.

| Runtime, DSpark3 in both | Repeat 1 output tok/s | Repeat 2 | Repeat 3 | Median |
|---|---:|---:|---:|---:|
| v0.27.1 | 519.33 | 535.37 | 545.05 | **535.37** |
| v0.32.0 | 538.20 | 549.86 | 543.95 | **543.95** |

The observed median difference is **+1.60%**. Three sequential finite repeats, overlapping repeat ranges and different host/cache state do not establish a robust speedup. Both runtime arms have 100/100 measured responses per repeat, zero request errors and complete completion usage. All six repeats have the same limited exact-arithmetic result, **13/37**; output-cap finishes remain 62–63 per repeat. These checks do not establish general code quality or numerical/text equivalence.

[Raw comparison, all six reports and individual outputs](results/serving-v032-20261115/serving-v032-comparison/) · [recomputed qualification audit](results/serving-v032-20261115/qualification-audit.json).

### Replay, interface and reasoning checks

- Each runtime completed **five repeats × four cheap-policy cases = 20 diagnostic cases** on one previously inspected pre-crash task. No controller or recorded transport error occurred. Model JSON parse errors remain in the traces: 29 old / 46 new. The final worker infrastructure count is unavailable for eight old and two new early stops; available final counts are zero. Those unknown counts are not zero-filled. Both old and new recipes passing this finite replay means the crash was not reproduced here, rather than proving the new image fixes it. [Old replay](results/serving-v032-20261115/serving-repro-v1-spark02/) · [new replay](results/serving-v032-20261115/serving-repro-v032-spark02/).
- New-image short JSON returned **100/100 at T0 and 100/100 at T0.8**. Each probe used **100 HTTP clients queued to one Spark's 25-sequence engine cap**. Four identical endpoint entries in the report refer to the same canary, not four replicas. The raw [T0](results/serving-v032-20261115/serving-v032-comparison/new-short100-t0.json) and [T0.8](results/serving-v032-20261115/serving-v032-comparison/new-short100-t0.8.json) reports retain all responses.
- The [tool probe](results/serving-v032-20261115/serving-v032-comparison/new-tool.json) passed a real `add(17,25)` tool call and returned `{"result":42}`.
- The [reasoning-on ensemble-4 smoke](results/serving-v032-20261115/v032-thinking-smoke/) reached target 10 from `1,2,3,4`, independently checked with exact `Fraction` transitions. Wall was **128.585s**, first observed verifier proof **127.264s**. One completed response retains reasoning and uses **156 prompt / 7,931 completion tokens**; three sibling responses were stopped. Client totals are lower bounds. Confirmed idle server-counter deltas cover **624 prompt / 31,752 completion tokens**, including stopped work. The final worker infrastructure count is **unknown/null**, with an expected controller exit `-15`; it is not inferred to be zero from the single completed response.

### Canary pins and export integrity

The [normalized launch receipt](results/serving-v032-20261115/canary-launch.json) records ARM64 image `vllm/vllm-openai@sha256:6ff5ff0ddf3658d2c2d677dac5ca2d4726ce0156b4371166d918181b210bd4bc`, canary loopback port 18097 and a separate `~/swarm-lab/cache-v032`. Flags retain TP1, 16,384 context, 25 sequences, 4096 batched tokens, memory utilization 0.70, Marlin MoE, FP8 KV, FlashInfer Mamba/align, prefix caching, chunked prefill and DSpark3. Reasoning/tool parsers are `nemotron_v3` / `qwen3_coder`. Target/draft revisions remain those in the historical pins below.

The [manifest](results/serving-v032-20261115/manifest.json) records **141 original artifacts**, original/export SHA-256 and exact path/interpreter substitutions, including custom replay source paths and the launch cache path. Parsed inverse checks preserve original values; model outputs and reasoning are retained, and unaffected files are byte copies. [Offline curation](results/serving-v032-20261115/curate.py) and [audit](results/serving-v032-20261115/audit.py) scripts are included. No model API was used for curation. These reports are serving qualification data and are excluded from primary task-quality aggregation.

## CPU grader image and disk headroom amendment

The [CPU grader amendment](CPU_GRADER_AMENDMENT.json) replaces the CPU-only grader's old ML image with pinned ARM64 `python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd`. Python changes **3.12.13 → 3.12.16**, GCC **11.4.0 → 14.2.0**, and glibc **2.35 → 2.41**. Only the coding grader's `IMAGE` constant changes; stdlib grading logic/isolation, model policies, prompts, budgets and corpora stay fixed. [357 reference cases / 48 phase containers plus three smoke validations](results/cpu-grader-20261115/cpu-python-grader-validation.json) pass, with zero owned leftovers on all four hosts. [Coding experiment notes](CODING_EXPERIMENT.md) retain the initial missing-reference-import failure and explain the finite scope of validation; no universal environment-parity claim is made.

The separate [Spark01 retirement receipt](results/cpu-grader-20261115/spark01-prototype-retirement.json) records retirement of the task-owned old v0.27.1 prototype and its image, with model/draft/cache directories retained for recreation. It records **65,945,247,744 bytes available AFTER the operation**. There is no before counter in that receipt, so this is not a measured reclaimed-byte delta. The small stdlib grader image removes the need to retain the ML image solely for CPU grading.

At this amendment stage, Spark01's v0.32.0 repull is complete and its final launch has started; the four-replica warm/readiness gate and fresh 900+80 study remain pending. CPU image validation and empty grading-container lists are separate from model-server readiness. The [CPU receipts and audit manifest](results/cpu-grader-20261115/manifest.json) preserve the original validation, initial invocation failure and retirement evidence. No v2 primary model calls occurred before this environment amendment.

## Historical v0.27.1: target-only versus DSpark3

On **Spark_02 (DGX Spark GB10, 128GB unified memory)**, DSpark3 produced a median
**528.02 completion tokens per full wall second**, versus **348.76** for the
target-only baseline: **+51.40% observed throughput**, with batch wall time
**47.314 → 31.226 seconds (−34.00%)**. These are three finite repeats per arm
at concurrency 25, measured on 2026-11-15, Europe/Warsaw.

This comparison supports selecting DSpark3 for the next bounded experiment on
this workload. It does not establish a universal concurrency optimum, a causal
gain across arbitrary workloads, or four-node scaling. A separate follow-up on
2026-11-15 verified health and real function round trips on all four replicas;
its measurements below have a different timing scope from these six reports.

## Measurements

| Configuration | Repeat / original suffix | Output tokens / wall second | Batch wall (s) | HTTP latency p50 (s) | HTTP latency p95 (s) | Length finishes / 100 |
|---|---|---:|---:|---:|---:|---:|
| Target-only | [2](results/serving-20261115/dspark-baseline-mixed-c25-2.json) | 348.76 | 47.314 | 16.299 | 17.195 | 62 |
| Target-only | [3](results/serving-20261115/dspark-baseline-mixed-c25-3.json) | 350.49 | 47.060 | 16.364 | 17.192 | 62 |
| Target-only | [4](results/serving-20261115/dspark-baseline-mixed-c25-4.json) | 348.54 | 47.323 | 16.012 | 17.562 | 63 |
| DSpark3 | [1](results/serving-20261115/dspark-mixed-c25-1.json) | 528.02 | 31.226 | 9.281 | 12.709 | 63 |
| DSpark3 | [2](results/serving-20261115/dspark-mixed-c25-2.json) | 527.51 | 31.296 | 9.208 | 12.373 | 63 |
| DSpark3 | [3](results/serving-20261115/dspark-mixed-c25-3.json) | 529.77 | 31.151 | 9.238 | 12.233 | 63 |
| **Target-only median** | Three clean repeats | **348.76** | **47.314** | **16.299** | **17.195** | — |
| **DSpark3 median** | Three repeats | **528.02** | **31.226** | **9.238** | **12.373** | — |

Latency medians above are medians of the three repeat-level percentiles, not
percentiles pooled across 300 requests. All six repeats returned **100/100 HTTP
responses, zero request errors, and complete server-reported completion-token
usage**. The baseline's original repeat 1 is excluded because a separate
two-request tool check overlapped it; only clean baseline repeats 2, 3, and 4
enter these aggregates.

## Workload and quality limits

Each repeat sends 100 non-streaming requests with 25 client workers, temperature
0, thinking disabled, and a 256-token output cap. Four sequential warmup requests
precede each repeat and are excluded from its measured wall time. Eight fixed
semantic tasks cycle through JSON arithmetic, Python generation, logic, and code
review. Every request carries a unique run-specific marker after the task;
semantic prompts stay fixed. Prefix caching remains enabled, so shared prefixes
may still be reused.

The metric is **server-reported completion tokens divided by the entire measured
batch wall time**. It includes prefill, client and server scheduling, and HTTP
overhead. It is not a sustained decode-only rate; TTFT and streaming inter-token
latency were not measured.

DSpark3 reaches the deliberate output cap on **63/100** requests in every repeat
(baseline: 62, 62, and 63). Long-form code, review, and logic answers may therefore
be incomplete. No code execution or code-success score is reported.

The three constrained JSON arithmetic task types are graded exactly: **13/37
pass and 24/37 fail in every repeat, in both arms**. Across three repeats that is
39/111 passing checks per arm. Equal limited-check counts do not establish broad
quality parity. Different response texts and completion-token totals are retained
in the reports; no exact token-equivalence claim is made. A separate two-call
`add(17, 25)` → `{"result": 42}` function round trip passed for both configurations;
its source hashes and outcomes are recorded in the summary, outside serving timing.

All baseline repeats ran before all DSpark3 repeats. This was not a randomized
or interleaved crossover, and three repeats do not quantify all host-state or
time-order effects.

## Four-replica follow-up

On **2026-11-15**, all four DSpark3 replicas passed their health checks and a real
two-call `add(17, 25)` → `{"result": 42}` tool round trip. Tool-check hashes and
outcomes are recorded separately from performance timing in `summary.json`.
Follow-up source: **`cbd97524dc10dbd779d726b3307bb4e0399a7622`**; the benchmark
script hash is unchanged from the primary comparison.

One concurrent four-node mixed batch, starting at 13:24:55 Europe/Warsaw,
completed **400 measured requests plus 16 warmups**, with **zero transport
errors**. The aggregate is **69,105 completion tokens / 40.029553 seconds =
1,726.35 completion tokens per full wall second**. Both the tokens and the full
wall time **include the warmups**. This differs from the primary warmed-repeat
metric, which excludes warmups; do not compare the two denominators as if they
were the same metric, or infer aggregate throughput by summing node rates.

| Node | Measured requests | Warmups | Warmed output tokens / wall second | Measured wall (s) | Exact JSON checks |
|---|---:|---:|---:|---:|---:|
| [Spark_01](results/serving-20261115/dspark-four-mixed-01.json) | 100 | 4 | 526.11 | 31.368 | 13/37 |
| [Spark_02](results/serving-20261115/dspark-four-mixed-02.json) | 100 | 4 | 523.93 | 31.504 | 13/37 |
| [Spark_03](results/serving-20261115/dspark-four-mixed-03.json) | 100 | 4 | 514.50 | 32.053 | 13/37 |
| [Spark_04](results/serving-20261115/dspark-four-mixed-04.json) | 100 | 4 | 520.32 | 31.705 | 13/37 |

Each node had 25 client workers and 63/100 measured responses ending at the
256-token cap. This is one four-node batch, not a repeated four-node scaling
study or a code-success benchmark. The original
[aggregate report](results/serving-20261115/dspark-four-mixed-summary.json)
records its exact full-wall denominator and node-file hashes.

Two separate four-node short-JSON formatting probes returned **100/100 correct**
agent IDs and answers: [temperature 0](results/serving-20261115/dspark-short-100.json)
and [temperature 0.8](results/serving-20261115/dspark-sampling-warmup-100.json).
They establish endpoint and formatting behavior for those short requests;
they are not mixed-workload throughput or puzzle-solving scores.

## Concurrency-one follow-up

A separate Spark_03 check used one 16-request batch per arm, concurrency 1,
temperature 0, thinking off, and the same 256-token cap. Four warmups per arm
were excluded. Source: `f506ae28d17b933939b62782141d6ccf6e0857aa`.

| Configuration | Output tokens / wall second | Measured wall (s) | HTTP p50 (s) | HTTP p95 (s) | Exact JSON checks |
|---|---:|---:|---:|---:|---:|
| [Target-only](results/serving-20261115/dspark-baseline-mixed-c1-node03.json) | 71.51 | 36.608 | 3.338 | 3.581 | 2/6 |
| [DSpark3](results/serving-20261115/dspark-mixed-c1-node03.json) | 98.62 | 26.546 | 2.327 | 2.764 | 2/6 |

The observed throughput difference is +37.90%. Both arms had zero request errors
and ten length finishes. This is **one batch per arm**, not the three-repeat c25
study; 2/6 exact checks in each arm do not establish general quality parity.

## Historical v0.27.1 runtime pins

Both arms use the same target and image:

- Target: `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, revision
  `bee7596271d1495f6992ae224aefde4410e816b8`.
- Runtime: `vllm/vllm-openai:v0.27.1`, pinned ARM64 manifest
  `sha256:1c8e60a0841b333c700488cb029d3664807249da0c071e862191b00fe34b228c`.
- Shared settings: TP1, context 16,384, max sequences 25, max batched tokens 4,096,
  GPU memory utilization 0.70, Marlin MoE, FP8 KV, FlashInfer Mamba,
  `mamba-cache-mode=align`, prefix caching and chunked prefill enabled.
- Candidate draft: `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark`,
  revision `6d127b50ecd98562cea85d0087680b7d86091fb0`, mounted read-only at `/draft`;
  `{"method":"dspark","model":"/draft","num_speculative_tokens":3}`.
- Target-only baseline: speculative decoding disabled.

The deployment script selects these arms through `SWARM_SPECULATION=none` or
`SWARM_SPECULATION=dspark`. It refuses to silently reuse a running container with
the other mode.

## Reproduction and provenance

Benchmark source: commit **`f506ae28d17b933939b62782141d6ccf6e0857aa`**;
[bench_serving.py](bench_serving.py) SHA-256
`3ee55dead5c73a0c7d5b02d1fb14f15d010ec527abc7ac158e4b7aded5549527`.
From this application directory, with an already-prepared endpoint:

```sh
python3 bench_serving.py http://127.0.0.1:18082/v1 \
  --model nemotron-lightning --concurrency 25 --requests 100 --max-tokens 256 \
  > serving-repeat.json
```

Port 18082 is the client's local tunnel to Spark_02 loopback port 18096. Run each
configuration three times with no concurrent probes. A follow-up study should
alternate or randomize configurations and include larger, independently graded
workloads before generalizing this gain.

[results/serving-20261115/summary.json](results/serving-20261115/summary.json)
contains exact values, original source paths, per-file SHA-256 hashes, pins,
aggregation definitions, exclusions, and tool-check provenance. The six curated
primary serving reports and nine additional follow-up reports are byte-for-byte
copies of the originals, including warmups, individual responses, errors, usage,
and timestamps. No response text was removed or rewritten. Follow-up evidence is
stored under its own summary key; the primary six-report metrics are unchanged.
