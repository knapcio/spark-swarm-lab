# Single-Spark serving: target-only versus DSpark3

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

## Runtime pins

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
