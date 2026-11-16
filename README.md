# Swarm Lab: verified agent search on four DGX Sparks

**Completed exploratory overnight study.** [Article draft](ARTICLE_DRAFT.md) · [X draft for the owner to publish](X_POST_DRAFT.md) · [DeepSeek reference](results/reference-deepseek-v1-analysis/REPORT.md) · [Reproduction guide](REPRODUCING.md). [Published raw evidence: 85.9 MB archive, manifests and checksums](EVIDENCE_RELEASE.md).

**Follow-up research is active:** [frozen 168-case emission/format experiment](FOLLOWUP72.md), informed by [Fable 5.2 high-effort design review](results/fable52-advisory-20261116/README.md) and independent diagnostics. No new Nemotron quality score is available yet; gains on the already-seen 24 tasks will be exploratory and separate from the frozen overnight release.

The frozen primary comparison covers 900 attempts:
24 arithmetic tasks and 18 Python-function tasks, three sampling seeds, and
strong solo, independent-ensemble, shared-state and voting controls. Repeated
seeds remain clustered by task. See [EVALUATION_SELECTION.json](EVALUATION_SELECTION.json)
for the primary protocol and [EVALUATION_PROGRESS.md](EVALUATION_PROGRESS.md)
for completed coverage and instrumentation exclusions. Development results below
do not establish a generally superior agent architecture.

A standard-library Python prototype for four independent Nemotron replicas.
Arithmetic moves are verified with `fractions.Fraction`. Generated Python
functions are evaluated separately in constrained, CPU-only Docker containers;
feedback tests guide repairs, and a frozen selected candidate receives one
held-out evaluation. See [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) for the design.

Each move consumes two indexed numbers and appends their result. Supported
operations are `+ - * /`; results must be positive integers. `--allow-fractions`
permits positive rational intermediate results. A game succeeds as soon as the
exact target appears; using all starting numbers is optional. The default puzzle
is `25,50,75,100,3,6:952`. One valid five-move solution exists.

## Research questions

Does cooperation improve exact puzzle success over independent search when
measured against actual prompt/completion tokens, request counts and wall time?
Can shared state or voting improve on independent whole-plan sampling and
sequential self-repair? The frozen comparison reports quality, latency and actual
costs; a separate single-policy queue experiment measures verified solutions per
minute under load. Reputation-weighted voting remains an exploratory prototype,
not a primary evaluation arm. Equal agent counts alone do not match budgets.
Preserve seeds, model/runtime/code revisions, calibration artifacts and JSONL
events so each experiment can be traced and repeated, while recognizing that
API seeds do not guarantee identical GPU execution.

## Current evidence

The separate native DeepSeek TP4 reference completed **72/72 arithmetic and 54/54 coding attempts**, on the same 24/18 tasks and three repetitions, with independent verification. This is a pinned custom abliterated checkpoint and a different serving/compute recipe, not an equal-cost model ranking. Native client usage is complete; global server token cost is unknown. [Reference comparison and limitations](results/reference-deepseek-v1-analysis/REPORT.md) · [independent audit](results/reference-deepseek-v1-audit/AUDIT.json). The planned Opus reference was unavailable because the account hit its weekly usage limit; the optional GLM hybrid was not run.

**Nemotron study runtime: vLLM 0.32.0 ARM64, DSpark3, four independent replicas.** These replicas are now stopped and retained; the saved native DeepSeek TP4 production service is restored after completing the separate quality reference. The uniform runtime-v2 study completed **900 primary attempts**, **80 supplemental solo-control attempts** (8 development and 72 evaluation), and **45 corrected loaded-queue cohorts / 2,016 attempts** (36 development batches and 9 evaluation batches). [Progress and exclusions](EVALUATION_PROGRESS.md).

The arithmetic primary four-sample reasoning ensemble solved **49/72 attempts (68.1%)**; sequential own-feedback refinement solved **45/72 (62.5%; task-cluster 95% interval 47.2–77.8%)**, versus **18/72 (25.0%)** for one reasoning call. The paired ensemble-minus-refinement difference is **+5.56 percentage points (95% interval −5.56 to +16.67)**, spanning zero. These are repeated attempts on **24 distinct tasks**, with separate execution schedules and different realized costs. [Completed stronger-solo comparison](results/solo-control-v2/complete-comparison/solo-comparison/REPORT.md).

Under load, shared frontier 8 recorded **12/96 successes at 21.31 successful attempts/minute**; four full plans recorded **48/96 at 2.87/minute**. These describe quality/rate tradeoffs for finite batches, not a universal efficiency winner. Admission was selected on development within **1/2/4/8 cases per node**; that bounded sweep does not establish globally optimal solo saturation. Four cheap-policy arms were a later exploratory amendment. [Completed throughput report, costs and figures](results/throughput-timeoutguard-20261115/REPORT.md).

Independent outer-parent coding confirmation completed **824 unique grading jobs for all 324 cases / 323 selected artifacts**. Original holdout outcomes agree in every case: **295 passes, 28 failures and one no-candidate failure**. Original scores are preserved; public examples and posthoc probes remain separate. This confirms finite test outcomes without repairing the original grader or proving general correctness. [Confirmation analysis](results/coding-confirmation-v1-analysis/NOTES.md) · [grader audit and limitations](CORRECTNESS_AUDIT.md).

The runtime-v2 serving qualification completed **416 mixed requests including warmups**, with **69,158 output tokens / 39.008007 full wall seconds = 1,772.918 output tok/s** and zero recorded transport errors. Separate short-JSON probes passed **100/100 at T0 and 100/100 at T0.8**. These bounded serving checks do not measure task-solving efficiency. The historical v0.27.1 DSpark comparison measured **+51.40%** on its particular matched workload; that is not a measured gain for the current runtime. [Serving reports and exact pins](SERVING.md).

The original [direct-assignment graph-search study](SEARCH_SELECTION.json) is complete: **0/252 core evaluation cases and 0/288 extended 64-call cases solved**. Across development and evaluation, 568 cases used 22,912 model calls, including reviewer reuse and ordinary/quality-weighted voting. Independent replay checked every one of 22,422 assignment proofs; malformed cardinality/domain responses were genuine candidate failures. The separately budgeted CPU controls solved 30/36 evaluation cases with min-conflicts and 18/36 with genetic search. [Independent audit](results/csp-independent-audit-20261116/FINAL_AUDIT.json).

In the separate [reusable-program experiment](PROGRAM_SEARCH_SELECTION.json), Nemotron wrote Python solvers scored only on four development graphs. Four independent chains selected programs solving **47/48 original evaluation outcomes**, compared with **29/48** for sequential refinement, at 16 training calls per program. These are **four paired trained programs per method on 12 reused graphs**, with wide uncertainty; generating a program and executing it on CPU is a different workflow from emitting assignments. [Completed report and figures](results/program-search-v1-analysis/REPORT.md) · [independent protocol audit](results/program-search-v1-audit/NOTES.md). Prospectively planned confirmation on **96 new graphs** is now complete: **376/384 (97.92%)** for independent chains and **237/384 (61.72%)** for sequential refinement. Three independent-chain programs each solve **96/96**; all eight sources were frozen before these 768 CPU-only grades, with zero extra model calls or repairs. [Fresh confirmation report, cost scope and figures](results/program-confirmation-v1-analysis/REPORT.md) · [independent audit](results/program-confirmation-v1-audit/AUDIT.json). The late exploratory reasoning-enabled assignment cohort also completed **0/96**: all **1,464 assignment calls** exhausted the 4,096-token cap in separate reasoning and returned no answer content; 72 review calls completed normally. This is an observed output-budget/format failure for this configuration, not evidence of general inability to color graphs. [Exact completed audit](results/csp-thinking-on16-late-audit-20261116/FINAL_AUDIT.json). Earlier assignment results remain unchanged.

The separate program-context reviewer experiment completed **47/48 original outcomes and 376/384 known-96 outcomes**, matching the independent-chain totals in these runs. Four training episodes each spent 16 calls: ten program proposals and six reviews. These late exploratory runs do not isolate a causal reviewer effect. [Completed report, costs and real review lineage](results/program-review-v1.1-analysis/REPORT.md) · [producer audit](results/program-review-v1.1-audit/FINAL_AUDIT.json) · [384-grade audit](results/program-review-confirmation-v1.1-audit/AUDIT.json). The pre-call phase-stop defect was fixed and [audited](results/program-review-precall-audit-20261116/PRECALL_AUDIT.json) before any variant calls.

The optional adversarial JSON-schema qualification passed 24 entries, then failed at 64 entries when a 512-token response ended in whitespace before completing JSON. It stopped after two calls; the third probe and 84-case quality study were not run. This is not a general backend-incompatibility result. [Exact qualification records](results/guided-schema-qualification-20261116/README.md) · [independent audit](results/guided-schema-qualification-v1-audit/AUDIT.json).

The saved four-agent DeepSeek pipeline check (`runs/pipeline-check-deepseek-4.jsonl`, local only)
made **24 calls**, using **341 completion tokens** and **2,952 prompt tokens**.
On `2,3,7,8:24`, democracy ended at **31**, so the exact target was not reached.
This checks the request, voting, evaluator and event pipeline; it is not a
Nemotron performance result or evidence of method superiority.

The historical target-only NemotronLightning baseline used four TP1 replicas on
vLLM **v0.27.1**. Its short 100-request JSON probe returned **100/100 correct** responses
in **1.759 seconds**, with **1,890 completion tokens** and **1,074.43 completion
tokens/second** aggregate. Server logs recorded a peak of **25 running requests
per replica**. This measures short-output serving throughput, not puzzle quality.

The [first 100-agent democracy pilot](results/traces/democracy-100-952.jsonl)
on target 952 completed **1,000 calls**, **16,595 completion tokens** in
**29.700536 seconds**, with **0 infrastructure failures** and **0 successes**.
This is one thinking-off run; it establishes neither method superiority nor a
thinking-on/off comparison. Comparative quality and the value of reputation
remain unestablished. See [PILOT.md](PILOT.md) for the independent run, a solved easy case, output-budget failures and included traces.

The separate [governance pilot](GOVERNANCE.md) includes an interleaved 18-run
follow-up with stable candidate identifiers: independent paths solved 2/6 games,
ordinary democracy 0/6, and democracy with verified-solution acceptance 1/6.
The 500-call ceiling censored every ordinary-democracy trajectory; these small,
stochastic experiments do not rank methods generally. Full prompts, costs and
negative earlier cohorts are retained. [PILOT.md](PILOT.md) also records reasoning
budget and reputation-pipeline checks.

## Quick start

Published evidence can be replayed without live models; see [REPRODUCING.md](REPRODUCING.md). The live-play commands below describe an active Nemotron study window. Its containers are currently stopped, and a new deployment window is required before those model endpoints can serve requests.

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

Fleet-specific operational note: the Nemotron experiment is closing and its containers are stopped. `fleet.sh` is the historical deployment adapter for this study; its `restore` path targets an older service and must not be used to restore the current native pico/dsgb10 production service. The verified native restoration uses the saved native service settings and an owner-checked release of the two study guard files after all reference work finishes. Fresh deployments require an explicitly scheduled fleet window.

Historical study configuration: `fleet.sh start` selected DSpark3 with the pinned draft (`download_draft.py`, 1.35 GB of weight files per node); `SWARM_SPECULATION=none` selected the target-only configuration. NFS and Spark_05–06 were preserved throughout the study.

Prototype containers use restart=no; start them explicitly after a reboot.
`connect.sh disconnect` closes only this prototype's four SSH forwards.

## Replay without GPUs

See [REPRODUCING.md](REPRODUCING.md) for fresh-checkout analysis, plots and own-endpoint commands, including grading and study-gate limitations.

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

The opt-in `--accept-verified-solution` policy accepts any already proposed,
exactly verified terminal candidate before voting. It applies to democracy and
weighted votes; independent paths already stop on exact success. It performs no
extra move generation or lookahead. The default keeps the original voting rule,
so both policies can be compared. The tree records `exact_target_verified` as the
selection reason and ends other branches without labeling them mathematically wrong.

A finite three-puzzle, two-seed experiment uses 100 agents and the same ceilings
of 500 calls and 96,000 completion tokens per run. Actual costs differ by method:

```sh
python3 run_study.py                 # Print the plan; no model calls
python3 run_study.py --run           # 12 independent/democracy runs
python3 run_study.py --run --include-guarded  # 18 interleaved policy runs
python3 run_study.py --run --method democracy --accept-verified-solution
```

Proposal identifiers are deterministic functions of seed, puzzle, depth, agent and
state, preventing random labels from changing voter inputs. Concurrent sampled
model responses can still differ across runs with the same seed.

Each invocation creates a new study directory with configuration hashes, commands,
raw events and actual-cost summaries. The six-run opt-in experiment is separate
from the original twelve-run experiment; inspect budget-limited outcomes explicitly.

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
