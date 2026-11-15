# Prompt calibration: example versus schema

Four sequential batches; one proposal per agent, no voting or search.

| Batch | Variant | Legal / 100 | Exact / 100 | Prompt tokens | Completion tokens | Wall s |
|---|---|---:|---:|---:|---:|---:|
| 1 | old | 98 | 0 | 12000 | 1461 | 1.80642 |
| 2 | schema | 42 | 4 | 13200 | 2160 | 2.128879 |
| 3 | schema | 44 | 4 | 13200 | 2145 | 1.662138 |
| 4 | old | 98 | 0 | 12000 | 1482 | 1.116948 |

Infrastructure failures: 0; budget denials: 0. All 400 responses were parseable
JSON and reported `finish_reason=stop`; usage was present for every request.
Exactly 25 requests per endpoint ran in each batch (concurrency cap 25 per
endpoint). Total: **400 calls, 50,400 prompt tokens, 7,248 completion tokens**;
summed batch wall time **6.714385 seconds**.

| Batch | `+` | `-` | `*` | `/` | Nonpositive-result errors | Noninteger-result errors |
|---|---:|---:|---:|---:|---:|---:|
| old 1 | 95 | 3 | 1 | 1 | 1 | 1 |
| schema 2 | 13 | 48 | 17 | 22 | 36 | 22 |
| schema 3 | 12 | 46 | 16 | 26 | 30 | 26 |
| old 4 | 96 | 3 | 0 | 1 | 1 | 1 |

Aggregating descriptive counts: old produced **0/200 exact** and **196/200
legal** actions; schema produced **8/200 exact** and **86/200 legal** actions.
The schema variant increased exact finishes in this probe while producing
**114 illegal actions**, versus **4** with the example prompt. These are
repeated batches of one state, not 200 independent puzzle evaluations per arm.
Repeated identical per-agent prompts and seeds returned the same parsed action
for **86/100 old** pairs and **70/100 schema** pairs; repeatability was not exact.

Operator distributions and every response/error are retained in summary.json and events.jsonl.

Only the final user-prompt sentence changes. Existing Client hashing derives the request seed from the full prompt, so variant changes also alter sampled RNG seeds. Repeated variants reuse agent seeds, but GPU batching may still differ. These batches concern one easy state, not held-out multi-step task quality. They do not establish a causal example-token bias, a general winning prompt, or agent-method superiority. Longer prompt length is included in actual token costs.

Reproduce with `python3 diagnostics/swarm-prototype-20261115/prompt-calibration/probe.py --run`; default invocation prints the plan without API calls. Source hashes, exact prompts/body settings and runtime snapshot are in metadata.json; each wire_response also retains the complete request body and raw HTTP response.
