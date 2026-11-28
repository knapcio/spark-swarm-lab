# Running and reproducing

[Landing page](../README.md) · [Mechanisms](mechanisms.md) · [Results](results.md) · [Method](method.md)

## Start with offline evidence

From the repository root, replay the included pilot traces without model servers:

```sh
python3 server.py --runs-dir results/traces --port 18777
```

Open http://127.0.0.1:18777. Select a run, move the timeline and inspect proposals and votes. The [reproduction guide](../REPRODUCING.md) covers the published study tag, analysis dependencies, table/figure rebuilding, archive checks and standalone own-endpoint experiments. For the current baseline counts, use [this public export](../results/default-baselines-20261128/REPORT.md).

## Current Inkling study runners

The swarm is idle by owner decision since 2026-11-27. The committed plans document a fleet-specific experiment environment; they are not a portable deployment recipe. The current serving configuration is the single-Spark recipe v2.9.2 on each of four nodes, behind the unchanged shim. [Measured recipe transition](../results/coding-v29-r2-v1/REPORT.md), [frozen serving and arithmetic configuration](../SWARM_FAIR_HARD23_PLAN.json), [coding configuration](../CODING_ELASTIC2_A_PLAN.json).

Prepare the pinned worker sources, then inspect each runner's plan without model calls or admission. These commands
create local Git worktrees; plan-only execution prints the job count without creating run directories:

```sh
git worktree add --detach ../swarm-arithmetic-source \
  "$(python3 -c 'import json; print(json.load(open("SWARM_BASELINE_HARD36_PLAN.json"))["source_revision"])')"
git worktree add --detach ../swarm-coding-source \
  "$(python3 -c 'import json; print(json.load(open("CODING_BASELINE_S85_PLAN.json"))["source_revision"])')"
python3 run_variants.py --plan SWARM_BASELINE_HARD36_PLAN.json \
  --source ../swarm-arithmetic-source --policy roll12fair --output runs/plan-arithmetic
python3 run_coding_earlystop.py --plan CODING_BASELINE_S85_PLAN.json \
  --source ../swarm-coding-source --output runs/plan-coding
```

The runners default to plan-only. A measured run needs the pinned source checkout, configured loopback tunnels, qualified serving/shim, CPU grading environment, a fresh admission and exclusive fleet lease. Admission checks bind the plan to that environment. Once a new fleet window is assigned and qualified, the study wrappers perform admission, cache flush, execution, final drain and accounting:

```sh
# Live fleet operations; examples for the qualified original environment only.
python3 inkling/arms.py --plan SWARM_BASELINE_HARD36_PLAN.json \
  --source PATH_TO_PINNED_ARITHMETIC_SOURCE --arm roll12fair \
  --output runs/new-arithmetic
python3 inkling/coding_arms.py --plan CODING_BASELINE_S85_PLAN.json \
  --output runs/new-coding
```

The coding wrapper reads `source_path` from its plan; it must point to the pinned source already prepared for that run. Output paths refuse overwrite. Do not fabricate admission receipts or use a historical restoration script to start current production. The [reproduction guide's grading limitations](../REPRODUCING.md#fresh-checkout-and-offline-checks) explain why there is no turnkey portable hardened coding CLI.

Serving setup: [Inkling single-Spark recipe](https://github.com/knapcio/Inkling-2-Mini-1x-DGX-Spark). The [original tuning record](../inkling/TUNING.md) describes the older cookbook/DSpark setup, not the final DFlash2 serving configuration. Keep administration and APIs on loopback/SSH or Tailscale; the high-speed fabric is a separate data path.

## Historical prototype commands

The commands below preserve the original interactive Nemotron workflow, defaults and event format. They do not run roll12fair or coding R2. Historical mentions of active follow-ups describe the original snapshot, not an active run today.

## Quick start

Published evidence can be replayed without live models; see [REPRODUCING.md](../REPRODUCING.md). The live-play commands below describe the historical interactive prototype. The separate fixed follow-up used dedicated measurement endpoints; interactive requests must not share a measured arm.

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
./play.sh democracy '1,2,3,4:10' 100
./play.sh independent '25,50,75,100,3,6:952' 100
```

`SWARM_CONCURRENCY=8` lowers simultaneous requests per endpoint while keeping
100 separate agents. `SWARM_SEED=2` changes seeded sampling. New runs appear in
the viewer. Weighted play accepts its calibration file as the fourth argument.

Fleet-specific operational note: the original overnight experiment has closed; the follow-up used a separately admitted measurement window. `fleet.sh` is the historical deployment adapter for this study; its `restore` path targets an older service and must not be used to restore the current native pico/dsgb10 production service. The verified native restoration uses the saved native service settings and an owner-checked release of the two study guard files after all reference work finishes. Fresh deployments require an explicitly scheduled fleet window.

Historical study configuration: `fleet.sh start` selected DSpark3 with the pinned draft (`download_draft.py`, 1.35 GB of weight files per node); `SWARM_SPECULATION=none` selected the target-only configuration. NFS and Spark_05–06 were preserved throughout the study.

Prototype containers use restart=no; start them explicitly after a reboot.
`connect.sh disconnect` closes only this prototype's four SSH forwards.


## Replay without GPUs

See [REPRODUCING.md](../REPRODUCING.md) for fresh-checkout analysis, plots and own-endpoint commands, including grading and study-gate limitations.

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
