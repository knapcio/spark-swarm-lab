# Mechanisms

[Landing page](../README.md) · [Results](results.md) · [Running](running.md) · [Method](method.md)

## Current swarm

Four independent Inkling-2-Mini replicas on four DGX Sparks, each serving through SGLang and the [dialect adapter](../inkling/shim.py). The swarm schedules independent attempts, replaces failures, and cancels siblings when a candidate is accepted. It does not use arithmetic-specific hints, decompositions or a task-specific solver to generate or select answers.

Arithmetic acceptance is a thinking model judge; the exact verifier scores the outcome separately. A rejected or missing plan triggers another independent attempt. Coding acceptance uses the supplied public tests; held-out tests score the selected winner and never select it. A wrong coding answer is an accepted winner that fails the hidden tests.

## Arithmetic: roll12fair

All cases are open from the start. A free agent slot goes to the case with the fewest agents in flight; ties prefer the fewest agents already started, then earlier case order. Limits are four agents in flight before a case's first failure, eight afterwards, and twelve agents total. Two permits per node are reserved for judges. The policy reads occupancy and failure counts, not elapsed time or task content.

| Change retained in the default | Measured effect | Evidence |
|---|---|---|
| Cancel siblings on acceptance | hard-v6: 83 versus 86 solved, 0 wrong; 33% fewer tokens, 36% less wall; owner adopted despite missing the frozen quality margin | [cancel](../results/swarm-cancel-hard6-v1/REPORT.md) |
| Failure-driven replacement | hard-v7: roll8cancel 90/96 versus deep4 82/96, 0 wrong; 19% fewer tokens, 21% less wall | [escalation](../results/swarm-escalate-hard7-v1/REPORT.md) |
| Cap twelve instead of eight | pooled hard-v12/v14: 173 versus 167/192, 0 wrong; four correct answers came from slots 9–12; hard-v14 costs 17% more tokens | [cap replication](../results/swarm-cap12-hard14-v1/REPORT.md) |
| Remove strategy hints | hard-v18: generic roll12cancel 85 versus hinted 83/96, 0 wrong; fewer tokens and Wh per solved | [generic policy](../results/swarm-generic-hard18-v1/REPORT.md) |
| Widen into idle capacity | hard-v20: 87/96 in both arms; wall 0.90x, GPU Wh 0.91x, tokens 1.01x | [widening](../results/swarm-wide-hard20-v1/REPORT.md) |
| Water-filling across cases | hard-v22: 82 versus 80/96; hard-v23: 88 versus 86/96; 0 wrong; wall 0.91x / 0.93x, tokens 0.90x in both | [first study](../results/swarm-fair-hard22-v1/REPORT.md), [replication](../results/swarm-fair-hard23-v1/REPORT.md) |

Water-filling improves batch throughput but increases time from case start to answer: medians 475 versus 218 seconds on hard-v22, and 567 versus 300 seconds on hard-v23. Single-task equivalence follows from the same limits with no competing cases; it was not measured separately. See [the batch comparison](../results/swarm-fair-hard23-v1/REPORT.md).

## Coding: R2 + code_elastic + cancel-on-accept

R2 keeps two agents in flight per case, replacing failures up to eight attempts. The first accepted public-test passer ends the case; remaining workers are terminated and queued workers never start. A hidden-test failure stays a wrong answer, not an abstention.

| Change retained in the default | Measured effect | Evidence |
|---|---|---|
| First passing proposal ends the case | 69 versus 66/72; tokens −37%, wall −36% versus all eight finishing | [early stop](../results/coding-earlystop-v1/REPORT.md) |
| R2 replaces staggered four-plus-four | first study: 71 versus 65/72, tokens −52%; replication: 71 versus 68/72, tokens −48%; pooled wrong 2 versus 8 | [R2](../results/coding-roll-v1/REPORT.md), [replication](../results/coding-roll2-v1/REPORT.md) |
| Continue length-cut answers | replication: 70/72 and 2 wrong in both arms; cut-off answers 0 versus 12; tokens 0.90x, wall 0.91x | [elastic replication](../results/coding-elastic-v2/REPORT.md) |
| Single-Spark recipe serving | v2.9 versus cookbook R2: 68 versus 67/72; wall −20%, GPU Wh −20% | [serving comparison](../results/coding-v29-r2-v1/REPORT.md) |

`code_elastic` retains the 30,720-token first call and continues only answers cut by length in 2,048-token steps. The per-agent completion cap is 40,960 rather than 32,768 (25% higher), with every token charged. Pooled elastic studies solved 140/144 with 4 wrong versus plain R2 141/144 with 3 wrong: adoption met the frozen tolerance; it is not an accuracy improvement. The earlier `code_reserve` lowered the thinking cap and was reverted after its replication failed. [Exact limits and reversal](../results/coding-elastic-v2/REPORT.md), [failed reserve replication](../results/coding-reserve-v2/REPORT.md).

## What did not become a default

| Mechanism | Outcome | Details |
|---|---|---|
| Burst escalation / three-wide arithmetic | Burst 90 versus 91/96 at higher cost; three-wide 81 versus 83/96 and 44% more wall | [burst](../results/swarm-burst-hard8-v1/REPORT.md), [width](../results/swarm-width3-hard11-v1/REPORT.md) |
| Judge critiques as repair context | 83 versus 86/96; escalation accepts 4/73 versus 9/82 | [repair](../results/swarm-repair-hard9-v1/REPORT.md) |
| One coding agent in flight | 66 versus R2 67/72; 30% more wall | [R1](../results/coding-roll3-v1/REPORT.md) |
| Extra idle-capacity agents beyond twelve | 86 versus 85/96; wall 1.24x, tokens +25% | [idle escalation](../results/swarm-generic-hard18-v1/REPORT.md) |
| Failed-artifact relay | Screens rescued 9 versus 2/43; inside the swarm 83 versus 84/96, compute +12% | [screens](../results/relay-screen-hard16-v1/REPORT.md), [swarm](../results/swarm-relay-hard19-v1/REPORT.md) |
| Atom-of-Thoughts | Arithmetic 82 versus 89/96, wall 2.15x; coding 66 versus 68/72 | [arithmetic](../results/swarm-aot-hard21-v1/REPORT.md), [coding](../results/coding-aot-v1/REPORT.md) |
| Lower-cap answer reserve | Replication 66/72, 6 wrong versus 71/72, 1 wrong; reverted | [reserve](../results/coding-reserve-v2/REPORT.md) |
| Live collaboration board | Corrected replay: 8 versus plain continuation 11 rescues/41; no live A/B | [S1 retest](../results/collab-s1-v2/REPORT.md), [closure](results.md#study-39) |
| Extension, forks, restatement, sibling holds | No confirmation rescue gain; forks 2 versus 4/12; restatement 0 versus 0/12; hold energy/solved 1.07x | [night summary](results.md#study-41) |
| Differential consensus gate | 213 versus 211/216, wrong 3 versus 5, energy/solved 1.87x; provisional STOP because transports differed | [live gate](../results/diffgate-live-v1/report.json), [limitations](results.md#study-42) |

The loop watchdog, table-relay prototype, dense relay window, extra judges, task-specific hints and prompt changes, no-tests coding, cache-placement bound and sampling-randomness proposal are all retained in the [complete experiment log](results.md). A stopped screen is not a universal impossibility result.

## Historical interactive prototype

The following describes the original Nemotron arithmetic game harness, retained for replay and small endpoint experiments. It is separate from the current whole-plan Inkling policies.

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
