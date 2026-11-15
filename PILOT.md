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
