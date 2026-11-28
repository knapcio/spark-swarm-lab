# Study method and decision rules

[Landing page](../README.md) · [Results](results.md) · [Mechanisms](mechanisms.md) · [Running](running.md)

## Frozen studies

Plans pin the corpus or prospective corpus generator, source revision, prompts, budgets, acceptance rule, arms, execution order and decision thresholds before calls. Fresh arithmetic confirmation corpora are generated after plan freeze. New coding seeds reuse the frozen task family; they are new attempts, not unseen tasks. [Original selection](../EVALUATION_SELECTION.json), [water-filling replication plan](../SWARM_FAIR_HARD23_PLAN.json), [elastic replication plan](../CODING_ELASTIC2_A_PLAN.json).

Screening recorded failures is development work. A promising screen requires a frozen confirmation on fresh work before adoption. Descriptive baseline runs have no adoption rule. Comparisons must state realized costs and differences in model, runtime, prompt or budget; equal agent counts do not imply equal compute.

## Replication rule

An efficiency win at a quality margin needs its replication before becoming the default. `code_reserve` illustrates why: the first study solved 71 versus 70/72; replication reversed that to 66 versus 71/72 with 6 versus 1 wrong. It was reverted. `code_elastic` retained the original first-call budget, passed the rule twice, and was adopted only after replication. Its extra answer budget and pooled wrong-count increase remain disclosed. [Reversal and investigation](../results/coding-reserve-v2/REPORT.md), [elastic confirmation](../results/coding-elastic-v2/REPORT.md).

Earlier owner decisions sometimes overrode a frozen efficiency or quality gate (arithmetic cancellation and the cap increase). Those exceptions stay explicit in the [log](results.md) and [changelog](../CHANGELOG.md); they are not retroactive changes to the rule.

## Acceptance, scoring and costs

Arithmetic model-judge acceptance is separate from exact scoring; the verifier never supplies search moves. Coding public tests guide acceptance and repairs; hidden tests score the winner without choosing or repairing it. Zero observed arithmetic errors do not prove a zero error rate. Coding baselines have observed hidden-test failures; passing public tests is not a correctness certificate.

Generated tokens for current Inkling comparisons come from server counters, including aborted requests. Arm wall and GPU-rail energy cover each arm alone through its final drain. GPU energy comes from the recorded nvidia-smi samples and excludes CPU, memory, NIC and fans; it is not wall-socket energy. DeepSeek client token usage is not interchangeable with swarm server counters. [Energy scope](../results/energy-defaults-20261122/tables.md), [comparison limitations](../results/deepseek-coding3-v1/REPORT.md).

Repeated seeds remain clustered by task. API seeds do not guarantee identical GPU samples; a later live probe found this serving launch did not honour request seeds. Pair by task outcomes, not by a claim of identical token streams. [Night disclosure](results.md#study-41).

Infrastructure faults, stop conditions, amended plans, full-arm reruns or permitted resumes, and wasted work must be reported. Earlier accounting scripts have known limits around cache-flush status, missing/reset counters, drain timeouts and energy errors; consult the study's own disclosures. [Water-filling disclosures](../results/swarm-fair-hard22-v1/REPORT.md). The differential-gate energy verdict remains provisional because the arms used different transports; its paired LAN rerun was held, not executed. [Full caveat](results.md#study-42).

## Rejection reviews

Rejected mechanisms received independent reviews of the gate, implementation and fairness of the control. The resulting disposition matters as much as the initial STOP:

| Review | Disposition and evidence |
|---|---|
| Loop watchdog | Replay found correct answers among flagged streams; provisionally not adopted; a less destructive trigger was proposed. [Log](results.md), [report](../results/swarm-loop-hard15-v1/REPORT.md) |
| Table-relay prototype | Rejected prototype; its capped builders made the screen unfair to the broader idea, which remains open. [Log](results.md) |
| Relay and Atom-of-Thoughts | Negative in-swarm or full-budget comparisons retained; rejections sent for review. [Relay](../results/swarm-relay-hard19-v1/REPORT.md), [AoT](../results/swarm-aot-hard21-v1/REPORT.md) |
| Failed reserve replication | Pairing by task remains valid; selection effects not excluded; retest retained the original thinking cap. [Investigation](../results/coding-reserve-v2/REPORT.md) |
| Collaboration | Review found the terminal-answer defect; corrected replay still lost to plain continuation. Closed for this board protocol on Inkling and these tasks. [Retest and closure](results.md#study-38) |
| Overnight generic ideas | Extension closed for this variant; fork STOP upheld as inconclusive; restatement parked for cost; hold-dispatch closed; coupled randomness requires a server change. [Dispositions](results.md#study-41) |
| Differential gate | Execution sound, comparison formally inconclusive; reject unchanged variant operationally and retest only a cheaper redesign with identical transport. [Review disposition](results.md#study-42) |

The dated log distinguishes a completed review, a review request and an unrun retest; none is silently promoted to a measured result.

## Original research questions

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


## Historical interactive budget accounting

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
