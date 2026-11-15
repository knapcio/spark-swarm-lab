# Swarm Lab: exact arithmetic, visible decisions

A standard-library Python prototype comparing independent search trajectories,
LLM democracy, and voting weighted by previous objectively scored games. No
model-written code is executed. The arithmetic evaluator uses `fractions.Fraction`.

Each move consumes two indexed numbers and appends their result. Supported
operations are `+ - * /`; results must be positive integers. `--allow-fractions`
permits positive rational intermediate results. A game succeeds as soon as the
exact target appears; using all starting numbers is optional. The default puzzle
is `25,50,75,100,3,6:952`. One valid five-move solution exists.

## Research questions

Does cooperation improve exact puzzle success over independent search when
measured against actual prompt/completion tokens, request counts and wall time?
Does reputation from separate objectively scored games help beyond equal votes?
The study will compare independent search, democracy and reputation-weighted
voting across held-out puzzles and seeds; equal agent counts alone do not match
budgets. Preserve seeds, model/runtime/code revisions, calibration artifacts and
JSONL events so each experiment can be traced and repeated, while recognizing
that API seeds do not guarantee identical GPU execution.

## Current evidence

**Current serving recipe: DSpark3 on four replicas**, with the same pinned target and vLLM image. Three same-node c25 repeats measured a median **528.02 output tokens/s**, versus **348.76** target-only (**+51.40%**). All four endpoints passed health and a real function-call round trip; the four-node short JSON probe returned **100/100 correct**. These are serving checks, not evidence of better reasoning. See [SERVING.md](SERVING.md) for prompts, raw reports, pins and limits. The original pilot below used target-only serving.

The saved four-agent DeepSeek pipeline check (`runs/pipeline-check-deepseek-4.jsonl`, local only)
made **24 calls**, using **341 completion tokens** and **2,952 prompt tokens**.
On `2,3,7,8:24`, democracy ended at **31**, so the exact target was not reached.
This checks the request, voting, evaluator and event pipeline; it is not a
Nemotron performance result or evidence of method superiority.

The fixed NemotronLightning baseline runs as four healthy TP1 replicas on vLLM
**v0.27.1**. A short 100-request JSON probe returned **100/100 correct** responses
in **1.759 seconds**, with **1,890 completion tokens** and **1,074.43 completion
tokens/second** aggregate. Server logs recorded a peak of **25 running requests
per replica**. This measures short-output serving throughput, not puzzle quality.

The [first 100-agent democracy pilot](results/traces/democracy-100-952.jsonl)
on target 952 completed **1,000 calls**, **16,595 completion tokens** in
**29.700536 seconds**, with **0 infrastructure failures** and **0 successes**.
This is one thinking-off run; it establishes neither method superiority nor a
thinking-on/off comparison. Comparative quality and the value of reputation
remain unestablished. See [PILOT.md](PILOT.md) for the independent run, a solved easy case, output-budget failures and included traces.

## Quick start

Run commands from this repository directory (`cd apps/swarm-lab` in the original workspace).

The read-only tree viewer is at http://127.0.0.1:18777 while `server.py` runs.
Select a run, move the timeline, and click a node to inspect proposals and votes.
`pipeline-check-deepseek-4.jsonl` is an explicitly separate pipeline check using
DeepSeek, not a Nemotron result.

```sh
# Four loopback SSH forwards to the prototype model servers:
./connect.sh
# Start the local viewer if it is not already running:
python3 server.py --port 18777
# In another terminal: method, puzzle, number of agents:
./play.sh democracy '25,50,75,100,3,6:952' 100
./play.sh independent '25,50,75,100,3,6:952' 100
```

`SWARM_CONCURRENCY=8` lowers simultaneous requests per endpoint while keeping
100 separate agents. `SWARM_SEED=2` changes seeded sampling. New runs appear in
the viewer. Weighted play accepts its calibration file as the fourth argument.

Fleet control: `fleet.sh status`, `fleet.sh start`, `fleet.sh stop`, and
`fleet.sh restore`. Start replaces the current DeepSeek service on Spark_01–04;
restore stops only the prototype containers and restores the saved current
DeepSeek via `~/dsgb10/window.sh prod`. NFS and Spark_05–06 are untouched.
`fleet.sh start` now selects DSpark3 and requires the pinned draft prepared on each node (`download_draft.py`, 1.35GB of weight files per node). To switch an existing replica, stop it first; a running mode mismatch is rejected. `SWARM_SPECULATION=none ./fleet.sh start` selects the original target-only fallback. Both modes retain the same restoration command.

Prototype containers use restart=no; start them explicitly after a reboot.
`connect.sh disconnect` closes only this prototype's four SSH forwards.

## Replay without GPUs

```sh
python3 server.py --runs-dir results/traces --port 18777
```

This reads the included English pilot traces. Live experiments write to `runs/`.
`fleet.sh` is the deployment adapter for this particular fleet; the experiment
harness itself only needs compatible API endpoints.

## Run

Python 3.10+; no packages or credentials required for the local endpoints.
Endpoints must serve OpenAI-compatible `/v1/chat/completions`. Each request sets
`chat_template_kwargs: {enable_thinking: false}` by default, `stream: false`,
a finite `max_tokens`, temperature 0.8, and a per-agent seed. Add `--thinking`
to enable reasoning while keeping the prompt unchanged. Reported completion
tokens include reasoning; the default 192-token cap may truncate a thinking
response before its JSON answer. For an explicit larger cap use
`--thinking --max-tokens 1024` and set the total completion budget accordingly;
no limit changes automatically. Model alias is `nemotron-lightning`.

Eight-agent smoke against a single endpoint (replace the address):

```sh
python3 harness.py --method democracy \
  --endpoint http://127.0.0.1:18081/v1 --model nemotron-lightning \
  --agents 8 --per-endpoint-concurrency 4 --rounds 5 \
  --max-tokens 192 --max-calls 80 --max-completion-tokens 15360 \
  --seed 1 --events runs/smoke-democracy-8.jsonl
```

One hundred agents across four endpoints, at most eight requests in flight per
endpoint (replace tunnel ports if needed):

```sh
python3 harness.py --method democracy \
  --endpoint http://127.0.0.1:18081/v1 \
  --endpoint http://127.0.0.1:18082/v1 \
  --endpoint http://127.0.0.1:18083/v1 \
  --endpoint http://127.0.0.1:18084/v1 \
  --model nemotron-lightning --agents 100 --per-endpoint-concurrency 8 \
  --rounds 5 --max-tokens 192 --max-calls 1000 \
  --max-completion-tokens 192000 --seed 1 \
  --events runs/democracy-100.jsonl
```

Use `--method independent` and a new events filename for the independent arm.
All output files refuse overwrite. URLs identify model servers only; no SSH,
remote configuration, downloads, generated-code execution or deployment occurs.
The process prints one JSON summary when done. A completed run may have
`budget_limited` or `complete_with_errors` status; inspect `run_end` before
interpreting its outcome. Network calls time out after 90 seconds by default;
there are no hidden retries.

## Methods

- `independent`: each agent pursues its own path for up to five moves. The group
  succeeds if any path reaches the target. Invalid proposals terminate that path.
- `democracy`: all agents independently propose a move from the same state.
  Duplicate resulting multisets are pruned. **Every agent then makes a separate
  model call to vote** among all distinct candidates; the winner becomes the
  next shared state. A tied tally uses first candidate order (lowest proposing
  agent ID), not an evaluator or solver. With no valid votes the game halts.
- `weighted`: the same process, but a vote weighs
  `(past_exact_successes + 1) / (past_games + 2)`. Agreement with other agents,
  distance to the target and candidate popularity do not train reputation.
- `calibrate`: independent games on a separate supplied puzzle list. Writes
  per-agent counts of exact binary successes for a later weighted run. A transport
  failure or exhausted budget prevents writing the reputation artifact; malformed
  model output is an unsuccessful path. No solver/oracle evaluates future moves.

For calibration, repeat the same four endpoints and other desired runtime flags:

```sh
python3 harness.py --method calibrate \
  --endpoint http://127.0.0.1:18081/v1 --model nemotron-lightning \
  --agents 8 --rounds 5 --seed 1 \
  --calibration-puzzles '25,50,75,100,2,4:810;25,50,75,100,3,5:650;1,3,7,10,25,50:765' \
  --reputation runs/reputation-8.json \
  --events runs/calibration-8.jsonl

python3 harness.py --method weighted \
  --endpoint http://127.0.0.1:18081/v1 --model nemotron-lightning \
  --agents 8 --seed 1 --reputation runs/reputation-8.json \
  --events runs/weighted-8.jsonl
```

A weighted run requires matching model alias, agent count, seed, thinking mode
and arithmetic rules, and rejects exact overlap between its puzzle and calibration puzzles.
Agent identity here is only model + seeded sampling stream, **not a learned
specialist**. Few calibration games may yield equal or noisy weights. The listed
calibration targets are examples, not a validated difficulty-balanced dataset.

## Budgets and comparability

`--max-calls` caps dispatched requests. `--max-completion-tokens` caps reserved
completion capacity; reservations occur after acquiring an endpoint slot. Actual
reported completion usage releases unused reservation. Missing usage or transport
failure conservatively charges that request's full `--max-tokens`. A server
violating `max_tokens` can exceed the total by already dispatched requests; the
actual report remains visible and prevents further reservations. Prompt tokens
are logged when reported, but are **not capped** by this completion budget.

At 100 agents and five rounds independent uses at most 500 calls; democracy and
weighted use at most 1000 (500 proposals + 500 votes). Thus equal agent counts
and rounds are **not equal compute**. Compare actual reported prompt/completion
usage, charged missing usage, requests and wall time. A fair quality study needs
multiple held-out puzzles/seeds and matched token or time budgets; this demo
does not establish statistical superiority of a method. API seeds do not promise
bitwise reproducibility across servers, batching schedules or runtime versions.
Endpoint concurrency controls hardware pressure; 100 logical agents can run
through fewer than 100 simultaneous requests.

## Events and viewing

Each JSONL record has `event_id`, UTC `timestamp`, `run_id`, `method`, `type`,
and puzzle context where applicable. Node state is a list of exact fraction
strings. Main records:

- `node`: `node_id`, `parent_id`, `state`, `depth`, `agent_id`.
- `proposal`: input `node_id`, `proposal_id`, `action`, `legal`, plus
  `child_node_id`/`child_state` or `error`.
- `vote`: `node_id`, `agent_id`, `candidate_id`, `valid`, `weight`.
- `chosen`: selected child `node_id`, previous `parent_id`, `candidate_id`, tally.
- `pruned`: child `node_id`, `parent_id`, reason.
- `reward`: terminal node, exact `solved`, binary `reward`, exact `distance`.
- `request_start`/`request_end`: request ID, agent, stage, endpoint index, latency,
  reported usage, conservative charge, response/error, `finish_reason` and optional
  `reasoning` text. A reasoning-only truncated response is an invalid proposal,
  not a transport failure. `budget_exhausted` and
  `halt` expose stopped work.
- `run_start`, `puzzle_start`, `puzzle_end`, `run_end`: configuration/outcomes.

The companion viewer/server, if present, reads these events. The harness is
independent of it. Logs contain model outputs and supplied puzzle numbers;
endpoint URLs are deliberately omitted from event configuration.

## Offline verification

```sh
python3 -m unittest discover -s . -p 'test_harness.py' -v
```

Tests check exact fractional arithmetic and a known 952 solution, illegal moves,
JSON-only parsing, concurrent budget reservations, conservative failed-request
charging, legal event parentage, independent paths, a real separate vote stage,
pruning, no-vote halt, overlap rejection, and failed-calibration artifact refusal.
They do not measure or assert GPU/model performance.
