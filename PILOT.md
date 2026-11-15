# First swarm pilot

2026-11-15, Europe/Warsaw. Four DGX Spark GB10 systems independently serve
Nemotron 3.5 Lightning NVFP4 with vLLM 0.27.1. Model and runtime pins are in
[runtime.json](runtime.json); serving recipe research is in
[RECIPE_RESEARCH.md](RECIPE_RESEARCH.md).

## Serving check

The client submitted 100 short JSON requests, 25 to each replica. All 100
returned the requested agent ID and answer. The batch completed in 1.759 s:
1,890 completion tokens, 1,074.43 output tokens per full wall second. Server
logs independently showed 25 active requests on every node. This checks serving
capacity and formatting, not puzzle-solving accuracy or sustained generation.

## Recorded experiments

All rows below used thinking off, temperature 0.8, seed 1 and a 192-token
per-request output cap. Arithmetic uses positive integer intermediates and
permits reaching the target with a subset of the original numbers.

| Method | Agents | Numbers and target | Requests | Input tokens | Completion tokens | Wall seconds | Solved |
|---|---:|---|---:|---:|---:|---:|---|
| Democracy | 100 | 25,50,75,100,3,6 → 952 | 1,000 | 338,500 | 16,595 | 29.701 | No; selected final value 850 |
| Independent paths | 100 | 25,50,75,100,3,6 → 952 | 478 | 60,043 | 7,125 | 7.286 | No; 0 of 100 paths solved |
| Democracy | 100 | 1,2,3,4 → 10 | 600 | 120,200 | 9,940 | 11.811 | Yes |

No transport failures or budget denials occurred in these three runs. They
establish that the prototype executes and records real proposals, voting,
pruning and exact outcomes across four replicas. One execution per case does
not establish a ranking of methods. Equal agent counts do not provide equal
compute: voting adds requests and longer prompts.

## Thinking smoke

A separate four-agent smoke enabled thinking with a 1,024-token cap on
2,3,7,8 → 24. All four proposal responses reached the output limit before
returning a valid action, consuming 4,096 completion tokens in 13.456 s.
This is an output-budget failure, not evidence that thinking cannot solve the
task. The CLI exposes thinking explicitly; reasoning tokens count toward its
completion budget. The current fast-worker baseline is weak on planning tasks.

## Follow-up: a larger reasoning allowance

Four independent agents generated exactly one next move for `2,3,7,8 → 24`,
with a 4,096-token cap, seed 1, and the original prompt unchanged. This directly
checks proposal generation; no votes or later search steps were used.

| Serving / thinking | Correct terminal proposals | Completion tokens | Length-limited responses |
|---|---:|---:|---:|
| Target-only / off | 0/4 | 60 | 0/4 |
| Target-only / on | 4/4 | 7,051 | 0/4 |
| DSpark3 / on | 2/4 | 16,012 | 2/4 |

The target-only on/off pair used the same Spark_03 endpoint, concurrency four,
cap and prompt. More reasoning improved this one task while consuming more
than 100 times the completion tokens. The DSpark row used Spark_02; seeded
sampling across decoding methods does not guarantee the same trajectories.
Its two failures exhausted the output cap before giving a parseable action.
These four-response samples do not establish decoder quality parity or
regression. A 4,096-token allowance is still insufficient for some samples.

[results/thinking-budget-20261115.json](results/thinking-budget-20261115.json)
contains costs, timings, hashes and portable traces. The
[pruning audit](PRUNING_AUDIT.md) distinguishes missing candidates from voting
away already proposed solutions; no symbolic solver was added.

## Reputation pipeline smoke

A 100-agent calibration used separate games `1,2,3,4 → 10` and `2,3,7,8 → 24`:
97 and 1 successful individual paths respectively, 597 calls, 8,857 completion
tokens and zero infrastructure failures or budget denials. Two-game Beta(1,1)
weights were 0.25 for three agents, 0.5 for 96, and 0.75 for one.

One held-out weighted-vote run on `3,5,7,9 → 24`, with verified-solution acceptance
enabled, used 500 calls and 8,260 completion tokens. It stopped at the call ceiling
without solving; 100 attempted vote calls were denied and no infrastructure failure
occurred. This verifies the calibration/artifact/loading/weighted-vote pipeline,
not an advantage from reputation. Its 597 calibration calls are additional cost.
Two games provide little evidence of stable worker skill; agent identity remains
a seeded stream of the same shared model. The artifact, raw portable traces and
hashes are in [results/reputation-smoke-20261115.json](results/reputation-smoke-20261115.json).

## Reproduction and evidence

[results/pilot-20261115.json](results/pilot-20261115.json) records configuration,
run IDs, source commits, costs, outcome flags and original trace hashes. The
original JSONL traces remain locally in `runs/`. Included copies in
`results/traces/` change only output-path metadata to portable relative paths;
both hashes are recorded. The read-only viewer can replay them with full or
collapsed duplicate branches, node details and a timeline, without a GPU.

For a quality study, use multiple held-out puzzles and seeds, a calibrated
per-call reasoning budget, and matched total-token or wall-time limits. The
weighted-vote path uses prior exact game outcomes; its implementation is tested,
but this pilot makes no empirical claim about reputation improving accuracy.
