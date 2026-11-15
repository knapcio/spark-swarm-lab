# Solo versus swarm: first controlled task batch

**Current primary evaluation (runtime v2.1).** The setup and development sections
below preserve the original development settings and interim reporting rules.
The completed 900 method–task–seed attempts use frozen source `cbcde299` and
vLLM 0.32.0. The [evaluation selection](EVALUATION_SELECTION.json),
[serving runtime amendment](RUNTIME_V2_AMENDMENT.json),
[CPU grader amendment](CPU_GRADER_AMENDMENT.json), and
[aggregate source configurations](results/evaluation-v2/primary-aggregate/source-configurations.json)
record the actual configuration and why the same tasks were rerun.

Arithmetic has ceilings of 1,280 calls and 32,768 completion tokens per case,
an 180-second task deadline, and per-call output caps of 8,192 with thinking on
or 192 with thinking off. Coding has ceilings of 1,024 calls and 131,072 completion
tokens per case, the same 180-second deadline, and output caps of 8,192 with
thinking on or 1,024 with thinking off. Final intervals resample task clusters
with all three seeds retained: 24 arithmetic tasks and 18 coding tasks. The
Wilson intervals described below were an interim reporting rule; the final
aggregate uses the recorded task-cluster bootstrap and paired comparisons.
This note changes no method, prompt, budget, dataset or historical record.

Research question: which use of a fixed Nemotron model produces the most
verified solutions for its elapsed time and inference cost?

This is a prototype study of synthetic arithmetic. It cannot establish the
best architecture for arbitrary coding, research or general agent work.
The earlier 36 governance runs and prompt probes are exploratory diagnostics,
retained separately rather than pooled with the new evaluation.

## Fixed resources and data

Four independent DGX Spark GB10 replicas run the same pinned Nemotron 3.5
Lightning NVFP4 target, DSpark3 draft and vLLM 0.27.1 image. See runtime.json
and SERVING.md for pins and measured serving behavior. No model weights change.

datasets/arithmetic-v1/tasks.json contains eight development tasks and 24
evaluation tasks. Both splits balance four and six starting numbers. Exact
reference witnesses are in a separate file that the benchmark runner never
loads. Previous task fingerprints, initially present targets and targets
reachable in one operation were excluded. Constructed witness length is not
a minimum solution depth or a calibrated difficulty label.

All methods use the same exact verifier: consume two indexed operands, retain
the other operands, append the result; operations +,-,*,/; strictly positive
integer intermediate values; using a subset is allowed. There is no solver
lookahead, distance-based selection or model-written code execution.

## Development comparison

Eight configurations run on development tasks before selecting evaluation
settings:

| Arm | Workers | Behavior | Thinking / per-call output cap |
|---|---:|---|---|
| direct_off | 1 | One complete JSON plan; verify without search | off / 192 |
| direct_thinking | 1 | Same complete-plan interface | on / 4096 |
| solo_steps_off | 1 | One sequential trajectory | off / 192 |
| solo_steps_thinking | 1 | Same sequential trajectory | on / 4096 |
| independent8 | 8 | Separate asynchronous trajectories | off / 192 |
| independent_rounds8 | 8 | Separate paths with round barriers and shared stopping | off / 192 |
| democracy8 | 8 | Propose, deduplicate, vote; accept exact solutions immediately | off / 192 |
| shared8 | 8 | Share verified states; deduplicate and retain a frontier of at most four | off / 192 |

Shared-frontier search uses a coordinator dictionary and recorded snapshots.
Workers consume states discovered by other workers in the following round.
The frontier rank is a deterministic hash independent of target distance.
This policy combines state sharing, deduplication and beam selection; it is
not a pure memory-only ablation. Its round-synchronous independent control
removes the barrier/stopping difference from that comparison.

Temperature is 0.8; seed label 1. Candidate identifiers are deterministic.
Concurrent GPU sampling can still produce different actions for the same seed.
Thinking allowances differ deliberately; measured costs must accompany accuracy.

Every case has ceilings of 128 calls and 32,768 completion tokens, at most five
moves/rounds, a 90-second HTTP timeout and a 180-second controller deadline.
Input tokens are measured, not capped. A deadline kills only the task's process
group. Its partial trace remains, its outcome counts as not completed by the
deadline, and unfinished inference usage is unknown rather than zero cost.

Four persistent slots each own one Spark endpoint. Arms rotate by task index;
all arms for a task use its assigned node. Each case is independent and gets
no notes or witnesses from other tasks. This stage measures task success,
latency and cost. It is explicitly not a saturated fleet-throughput test.

## Evaluation and reporting rules

Development outcomes select a practical solo configuration and promising swarm
policies. Record that selection and its rationale before sending evaluation
tasks. Do not change prompts, reasoning caps or selection rules after seeing
evaluation results; further revisions need a new dataset or an explicitly
exploratory label. Keep negative and budget-limited outcomes.

Report successes/24 with Wilson intervals, per-task paired outcomes, median
and tail latency, calls, input/output tokens, response errors, deadlines and
infrastructure failures. Output-token counts include reasoning. Token counts
are not interchangeable with GPU time. Group success means any verified
solution, not an average worker vote or an approximate numerical answer.

Fleet throughput needs a separate queue measurement on the same four nodes.
Measure actual queue wall time; do not sum overlapping case durations. Increase
task concurrency for solo as well as groups, and disclose when the finite task
batch cannot fill every serving slot. A gain over underbatched solo does not
by itself demonstrate useful collaboration. Compare collaborative policies
against parallel independent sampling, then test larger groups only if useful.

Save raw JSONL, public tasks, configuration/source hashes and CSV/JSON summaries.
Figures for the eventual X article must be generated from those summaries;
label exploratory cohorts, task scope, costs and uncertainty. Keep the public
GitHub repository updated. Prepare an X draft at the end; the owner will publish it.

## Development amendments before evaluation

The 4K reasoning allowance truncated six of eight direct answers and every
stepwise-thinking development case. Additional development cohorts therefore
calibrate 8K full plans, full-plan ensembles of two/four workers, and cascades
that try cheap independent paths before one 8K full-plan fallback. Separate
development sweeps compare group sizes 8, 32 and 100. Their common call ceiling
is 1,280, permitting complete 100-worker proposal/vote rounds; actual calls and
tokens remain the relevant costs. Earlier 128-call cohorts remain separate.

An optional controller stops on a recorded exact-verifier success, cancels its
owned process group and waits for the endpoint to become idle. Partial client
usage is a lower bound; server counter deltas are used only with valid idle
snapshots and counters consistent with completed client usage. Unknown costs
remain unknown. Sources run in detached worktrees so ongoing implementation
changes cannot silently change a cohort. Evaluation has not been used to tune
these amendments.

## Related work

| First public date | Primary work | Relevant scope |
|---|---|---|
| 2022-03-21 | [Self-Consistency](https://arxiv.org/abs/2203.11171v4) | Samples reasoning paths from one model and aggregates final answers on arithmetic and commonsense QA. |
| 2023-03-30 | [Self-Refine](https://arxiv.org/abs/2303.17651v2) | One model generates, critiques and revises its output across seven tasks. |
| 2023-05-17 | [Tree of Thoughts](https://arxiv.org/abs/2305.10601v2) | Searches intermediate thoughts using model evaluation; includes Game of 24, writing and crosswords. |
| 2023-05-23 | [Multiagent Debate](https://arxiv.org/abs/2305.14325v1) | Model instances exchange rationales and revise answers; the main setup uses three agents and two rounds. |
| 2023-08-18 | [Graph of Thoughts](https://arxiv.org/abs/2308.09687v4) | Represents intermediate information as a graph with aggregation and feedback operations. |
| 2024-02-03 | [More Agents Is All You Need / Agent Forest](https://arxiv.org/abs/2402.05120v2) | Studies sampling and answer/similarity voting; gains depend on task difficulty. |
| 2025-02-12 | [Stop Overvaluing Multi-Agent Debate](https://arxiv.org/abs/2502.08788v3) | Five debate methods, nine benchmarks and four models: debate often fails to beat CoT or self-consistency despite more computation. |
| 2026-04-29 | [The Cost of Consensus](https://arxiv.org/abs/2605.00914v1) | Compares ten-agent debate with ten isolated revision tracks; examines conformity and communication costs, with output-cap and model-scope caveats. |

These findings concern their published models, tasks and budgets, not this fleet.
Our arithmetic ensembles accept any exactly verified solution; this differs from
majority voting or free-form debate. Same-model samples can share a preferred
wrong answer, so consensus alone does not establish correctness. Coding feedback
tests also do not prove that a candidate will pass the separately frozen holdout.

Our sequential refinement uses external verifier/test feedback, whereas Self-Refine
emphasizes model-generated feedback. Shared8 combines state handoff, deduplication
and frontier selection; it is not a pure memory ablation or shared GPU attention
cache. This context does not amend the frozen methods. The [structured review](results/related-work-20261115.json)
records versions, author repositories and comparison limits; dates above are first
arXiv submissions, not necessarily venue publication dates.
