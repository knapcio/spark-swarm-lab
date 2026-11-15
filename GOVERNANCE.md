# Preliminary governance experiment — 2026-11-15

Twelve baseline runs compare 100 independent paths with one shared path chosen by 100-agent unweighted proposal/vote rounds. Independent search solved 2 of 6 puzzle/seed games; democracy recorded 0 of 6, with all six democracy runs censored by the 500-call limit. This does **not** establish inferior voting quality. On both solved-by-independent puzzle instances, democracy had already proposed exact solutions but had no budget left to vote on them.

## Scope and interpretation

- Three fixed arithmetic puzzles, seeds 1 and 2, each method; no calibration or reputation weighting. These are a small diagnostic pilot, not an independent benchmark sample.
- Same ceilings per run: 500 model calls and 96,000 completion tokens; 100 agents; thinking OFF; 192-token response cap; at most five rounds; four endpoints with 25 concurrent slots each. Same ceilings do not mean matched actual cost. Prompt tokens are reported separately and are outside the completion ceiling.
- Independent success means **any one of its 100 paths** reaches the target. Democracy success means its **one selected shared path** reaches the target. Those are different search policies and opportunities, not 100 separate democracy games.
- Legal moves consume two indexed values and append their positive integer arithmetic result. Any subset of original numbers may be used; success is target presence in the state, not necessarily a singleton state. Witnesses in metadata were not sent to agents.
- Runtime metadata records four TP1 GB10 replicas, official vLLM 0.27.1, NVFP4 target plus DSpark3. The metadata itself is a configuration snapshot; no fresh API or GPU verification was performed during this curation.
- Seed labels do not imply bitwise reproducibility across concurrent GPU scheduling. Guarded terminal-solution acceptance is a separate follow-up documented below; it is not included in the baseline tables.

## Per-run results

Calls are actual dispatched/completed requests. Prompt and completion are sums of server-reported usage. Wall time is the original controller measurement (seconds), including process startup/teardown. Individual successes count independently checked final outcomes out of 100, not statistically independent trials.

| Puzzle | Seed | Method | Recorded solved | Successful individual paths | Calls | Prompt tokens | Completion tokens | Wall s | Budget denials | Status |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| P1 | 1 | democracy | no | — (one shared path) | 500 | 108,700 | 8,148 | 11.445683 | 100 | budget_limited |
| P1 | 1 | independent | no | 0/100 | 299 | 34,231 | 4,310 | 5.119980 | 0 | complete |
| P1 | 2 | democracy | no | — (one shared path) | 500 | 93,000 | 8,032 | 9.684066 | 100 | budget_limited |
| P1 | 2 | independent | no | 0/100 | 300 | 34,333 | 4,331 | 4.627727 | 0 | complete |
| P3 | 1 | democracy | no | — (one shared path) | 500 | 233,000 | 8,106 | 13.385302 | 100 | budget_limited |
| P3 | 1 | independent | no | 0/100 | 481 | 59,220 | 7,160 | 5.962953 | 0 | complete |
| P3 | 2 | democracy | no | — (one shared path) | 500 | 225,000 | 8,070 | 15.001897 | 100 | budget_limited |
| P3 | 2 | independent | no | 0/100 | 490 | 60,294 | 7,242 | 8.379494 | 0 | complete |
| P2 | 1 | democracy | no | — (one shared path) | 500 | 114,900 | 8,256 | 11.655553 | 100 | budget_limited |
| P2 | 1 | independent | yes | 87/100 | 294 | 33,711 | 4,265 | 3.836459 | 0 | complete |
| P2 | 2 | democracy | no | — (one shared path) | 500 | 114,100 | 8,233 | 10.215975 | 100 | budget_limited |
| P2 | 2 | independent | yes | 84/100 | 292 | 33,496 | 4,286 | 3.462188 | 0 | complete |

Puzzles: P1 = `2,3,5,9 → 28`; P2 = `3,5,7,9 → 24`; P3 = `2,4,7,9,25,50 → 684`.

## Why the democracy result is budget-censored

Every democracy run used 300 proposal calls and 200 actual vote calls: two complete 100-proposal/100-vote rounds plus a third 100-proposal round. The third round then attempted 100 votes with the call budget already at 500. All were denied before dispatch; traces contain 300 `vote` events but only 200 actual vote requests. The remaining 100 vote events are invalid local consequences of budget denial, not sampled model votes. The shared state therefore advanced only twice and halted with `no_valid_votes`.

| P2 instance | Final selected state | Third-round exact-target proposals | Third-round actual vote requests | Denied vote requests | Recorded result |
|---|---|---:|---:|---:|---|
| Seed 1 | `[9, 15]` | 94/100 proposals yield `[24]` | 0 | 100 | unsolved / budget_limited |
| Seed 2 | `[7, 17]` | 89/100 proposals yield `[24]` | 0 | 100 | unsolved / budget_limited |

The 94 and 89 counts are legal proposals, including duplicates, not unique solutions or completed successful paths. Both states have a direct legal addition to 24. Acceptance required the absent final vote stage in this baseline. An additional complete 100-agent vote round would require 600 total calls for this trajectory; the baseline ceiling was 500. This documents a protocol/budget interaction, not what the unobserved votes would have selected.

For P1 the final shared states were `[2, 17]` and `[9, 10]`; for P3 they were `[2, 4, 7, 475]` and `[2, 7, 9, 225]`. No legal target-reaching proposal was recorded for those four runs. They were also budget-limited before selecting a third move; their eventual outcomes remain unobserved.

## Aggregate actual cost

| Method | Solved games | Individual successes | Actual calls | Prompt tokens | Completion tokens | Sum of run wall s | Budget denials |
|---|---:|---:|---:|---:|---:|---:|---:|
| independent | 2/6 | 171/600 paths | 2,156 | 255,285 | 31,594 | 31.388801 | 0 |
| democracy | 0/6 | — | 3,000 | 888,700 | 48,845 | 71.388476 | 600 |

All runs have zero reported infrastructure failures and complete prompt/completion usage. Model response-format errors remain in the traces and must not be confused with infrastructure failures. Returning process code 0 also does not mean that a puzzle was solved.

## Export integrity and portability

The curated [baseline directory](results/governance-20261115/baseline/) contains 12 JSONL traces plus metadata, summary and [manifest](results/governance-20261115/baseline/manifest.json). Run commands assume the current working directory is the `swarm-lab` project root. Endpoint ports remain the original local tunnel ports; replaying a command still requires the corresponding model-serving setup.

Original files in `runs/dspark-study-20261115/` were not changed. Trace exports modify only `run_start.config.events` and `run_end.events`. Summary exports modify only each row’s `events`. Metadata exports modify only `runs[].events`, the matching `command` event argument, the interpreter to `python3`, and the absolute project/HERE prefix to `.` (`./harness.py`). All other bytes, including whitespace, event IDs, timestamps, usage, contents, outcomes and metadata source hashes, are retained.

The manifest records every exact replacement and both original/export SHA-256 values. All 14 files passed a reverse-normalization byte-identity check. The audit also checked contiguous event IDs, matched request IDs, usage totals against summary/run_end, each legal arithmetic transition using exact fractions, final independent outcomes, terminal proposal counts and budget denials. No inference API was called.

## Guarded-democracy follow-up — protocol v1

Six additional live runs enabled `--accept-verified-solution`, preserving the same ceilings, 100 agents, thinking OFF and 192-token response cap. Source commit: `1b006d8f722dbd40959a366b5cbf7aadbdc7f161`; exact source-file hashes remain in the exported metadata and manifest. The guard accepts a legal exact-target proposal before another paid vote round. It is an intervention in the governance protocol, not a new model or decoding recipe.

**Observed live result: 0/6 solved, all six budget_limited, zero target-reaching legal proposals and zero guard acceptances.** Unlike the original P2 democracy runs, this cohort never generated a target proposal for the guard to accept. Do not claim that this live cohort rescued the baseline terminal proposals, or that the guard reduced their cost. Such a counterfactual is not measured by these runs.

| Puzzle | Seed | Final selected state | Terminal proposals | Recorded solved | Calls | Prompt tokens | Completion tokens | Wall s | Budget denials |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|
| P1 | 1 | `[2, 17]` | 0 | no | 500 | 103,800 | 7,985 | 9.312922 | 100 |
| P1 | 2 | `[5, 8]` | 0 | no | 500 | 103,400 | 7,864 | 9.037713 | 100 |
| P2 | 1 | `[7, 18]` | 0 | no | 500 | 113,700 | 8,169 | 14.318619 | 100 |
| P2 | 2 | `[5, 84]` | 0 | no | 500 | 118,800 | 8,078 | 13.216087 | 100 |
| P3 | 1 | `[2, 4, 25, 457]` | 0 | no | 500 | 243,600 | 7,954 | 14.071248 | 100 |
| P3 | 2 | `[2, 4, 9, 375]` | 0 | no | 500 | 231,900 | 7,933 | 15.690738 | 100 |

Total actual cost: **3,000 calls**, **915,200 prompt tokens**, **47,983 completion tokens**, **75.647327 summed run seconds**, and **600 budget denials**. Each run dispatched 300 proposal and 200 vote requests, then denied 100 further vote requests. All runs report zero infrastructure failures and complete token usage; format errors remain separately visible in traces.

Guarded P2 finished at `[7, 18]` and `[5, 84]`, rather than the original `[9, 15]` and `[7, 17]`. Those changed trajectories prevent a simple paired attribution of their outcome to terminal acceptance alone. These six negative outcomes are retained alongside all 12 original baseline runs.

Curated [guarded traces and metadata](results/governance-20261115/guarded/) and [manifest](results/governance-20261115/guarded/manifest.json) apply the same normalization policy as the baseline. All eight exports passed reverse-normalization byte-identity checks; all original files were preserved. The audit replayed every legal arithmetic transition, checked final states and the absence of terminal proposals, matched dispatched/completed request IDs, verified usage totals, and counted budget denials. No API was called during curation.

## Motivation for protocol v2

The protocol-v1 candidate IDs were random UUIDs. Candidate IDs were included in voting input, and request seeds were derived from prompt content. Consequently a constant user seed did not guarantee identical vote input or identical model sampling seeds across reruns. This is a concrete source of avoidable cross-run variation; it is a hypothesis about the changed trajectories, not proof that it caused these particular failures. Concurrent GPU execution can also introduce variation.

Protocol v2 replaces random candidate IDs with stable IDs, as documented in the new cohort below. The protocol-v1 baseline and guarded follow-up remain intact; neither was rewritten or merged into a claimed controlled estimate of guard effect.

## Protocol v2 — stable candidate IDs, 18 live runs

Source commit: `f551b56f97d515b4981382be4b16a06e2caa773c`. Proposal IDs are the first 12 hexadecimal characters of SHA-256 over JSON `[seed, puzzle_id, depth, agent_id, canonical_state]`; the audit recomputed every proposal ID from its recorded parent state. Node/run/request IDs remain trace identifiers, distinct from these stable candidate IDs.

Three arms were interleaved for each puzzle: seed1 ran independent → democracy → guarded democracy; seed2 reversed that order. All retain the same 500-call/96,000-completion ceilings, 100 agents, thinking OFF, 192-token response cap and original serving configuration. Later calibration or weighted-democracy smoke tests are not part of this cohort.

**Observed results:** independent **2/6**, democracy **0/6**, guarded democracy **1/6**. The guarded P2/seed1 trace demonstrates one actual verified terminal acceptance. These small, stochastic cohorts do not establish a general ranking or a paired causal effect of the guard.

| Puzzle | Seed | Arm | Solved | Successful individual paths | Calls | Prompt tokens | Completion tokens | Wall s | Budget denials | Terminal proposals | Status |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| P1 | 1 | independent | no | 0/100 | 299 | 34,233 | 4,326 | 3.386791 | 0 | 0 | complete |
| P1 | 1 | democracy | no | — | 500 | 119,500 | 7,981 | 7.992402 | 100 | 0 | budget_limited |
| P1 | 1 | democracy-guarded | no | — | 500 | 98,300 | 7,955 | 7.494784 | 100 | 0 | budget_limited |
| P1 | 2 | democracy-guarded | no | — | 500 | 114,100 | 7,895 | 7.934028 | 100 | 0 | budget_limited |
| P1 | 2 | democracy | no | — | 500 | 113,900 | 7,924 | 8.077699 | 100 | 0 | budget_limited |
| P1 | 2 | independent | no | 0/100 | 300 | 34,339 | 4,345 | 3.384134 | 0 | 0 | complete |
| P2 | 1 | independent | yes | 78/100 | 289 | 33,146 | 4,308 | 3.661307 | 0 | 78 | complete |
| P2 | 1 | democracy | no | — | 500 | 114,400 | 7,970 | 8.289600 | 100 | 98 | budget_limited |
| P2 | 1 | democracy-guarded | yes | — | 500 | 119,600 | 8,125 | 10.243287 | 0 | 97 | complete |
| P2 | 2 | democracy-guarded | no | — | 500 | 104,000 | 7,989 | 7.377167 | 100 | 0 | budget_limited |
| P2 | 2 | democracy | no | — | 500 | 114,400 | 8,246 | 9.286289 | 100 | 95 | budget_limited |
| P2 | 2 | independent | yes | 85/100 | 294 | 33,714 | 4,307 | 3.537101 | 0 | 85 | complete |
| P3 | 1 | independent | no | 0/100 | 495 | 60,881 | 7,392 | 6.113396 | 0 | 0 | complete |
| P3 | 1 | democracy | no | — | 500 | 225,100 | 7,808 | 12.023391 | 100 | 0 | budget_limited |
| P3 | 1 | democracy-guarded | no | — | 500 | 229,400 | 8,031 | 12.734954 | 100 | 0 | budget_limited |
| P3 | 2 | democracy-guarded | no | — | 500 | 248,900 | 8,006 | 13.625144 | 100 | 0 | budget_limited |
| P3 | 2 | democracy | no | — | 500 | 243,700 | 8,118 | 14.154895 | 100 | 0 | budget_limited |
| P3 | 2 | independent | no | 0/100 | 488 | 60,062 | 7,252 | 6.011398 | 0 | 0 | complete |

### Protocol-v2 aggregate actual cost

| Arm | Solved games | Successful individual paths | Actual calls | Prompt tokens | Completion tokens | Sum of run wall s | Budget denials |
|---|---:|---:|---:|---:|---:|---:|---:|
| independent | 2/6 | 163/600 | 2,165 | 256,375 | 31,930 | 26.094127 | 0 |
| democracy | 0/6 | — | 3,000 | 931,000 | 48,047 | 59.824276 | 600 |
| democracy-guarded | 1/6 | — | 3,000 | 914,300 | 48,001 | 59.409364 | 500 |

### Verified terminal acceptance and budget censoring

P2/seed1 guarded democracy reached selected state `[5, 19]`; 97 legal third-round proposals produced `[24]`. The trace selected candidate `1257b8c46c32` at event 2084 with reason `exact_target_verified`, advancing to `[24]` without a third vote round. It spent **500 calls** (300 proposal + 200 vote), had **zero budget denials**, and ended `complete`. Hitting the call ceiling is not by itself a `budget_limited` outcome when no further call is needed.

Unguarded P2/seed1 and P2/seed2 both stopped at `[5, 19]`, with respectively 98 and95 legal target-reaching third-round proposals, but their 100 final votes were denied. They remained `budget_limited` and unsolved. The five other guarded runs contained zero target-reaching legal proposals and also denied 100 final votes each. Thus all six unguarded and five guarded runs were budget-censored.

### Stable IDs did not make trajectories identical

At the first root, democracy and guarded democracy have the same puzzle/state, seed, task and 100 matching candidate IDs. Nevertheless their model outputs already diverged before any terminal guard could act. Comparison by agent ID gives:

| Puzzle | Seed | Candidate ID differences /100 | Parsed action differences /100 | Raw response differences /100 | Legality differences /100 |
|---|---:|---:|---:|---:|---:|
| P1 | 1 | 0 | 33 | 36 | 0 |
| P1 | 2 | 0 | 19 | 19 | 1 |
| P2 | 1 | 0 | 17 | 18 | 4 |
| P2 | 2 | 0 | 17 | 20 | 2 |
| P3 | 1 | 0 | 19 | 19 | 1 |
| P3 | 2 | 0 | 25 | 25 | 0 |

Parsed action differences compare decoded `action` objects, including null parse failures; raw response differences also include formatting. The manifest records the affected agent IDs for every comparison. Stable IDs remove one avoidable prompt/seed perturbation, but do **not** guarantee equal sampled outputs, GPU execution, cache/serving history or later search trajectories. The observed root differences rule out treating these arm runs as identical paired trajectories differing only at final acceptance; they do not identify which remaining source caused the variation.

### Protocol-v2 export integrity

The [stable-ID export](results/governance-20261115/stable-ids/) contains 18 traces, metadata, summary and a [manifest](results/governance-20261115/stable-ids/manifest.json). All 20 files reverse-normalize to byte-identical originals. Allowed edits remain only the two trace event-path fields, summary event paths and metadata event paths/interpreter/HERE prefix. Source commit/hash values, guard flags, outputs, usage, event IDs and timestamps are retained.

The audit checked exact arithmetic for all legal proposals, stable proposal hashes, final path outcomes, token/call accounting, budget denials, guarded selection reason and absence of third-round vote requests at that selected state. All original baseline, negative guarded-v1 and protocol-v2 cohorts remain preserved. No API was called during this curation.
