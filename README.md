# 🐝 Swarm Lab on four DGX Sparks

Generic agent scheduling, verification and cancellation with **Inkling-2-Mini on 4× NVIDIA DGX Spark**.

[Results](docs/results.md) · [Mechanisms](docs/mechanisms.md) · [Running](docs/running.md) ·
[Method](docs/method.md) · [Changelog](CHANGELOG.md)

## Headline results

Current-default baselines, completed by 2026-11-28. Counts are attempts; coding repeats the same tasks with new
sampling draws. These descriptive runs do not compare alternative policies.

| Current default | Scope | Solved | Wrong |
|---|---|---:|---:|
| **Arithmetic: roll12fair** | 11 hard sets, hard-v26–v36 | **947/1,056**; mean **86.1/96** | **0** |
| **Coding: R2 + code_elastic + cancel-on-accept** | 10 baseline cohorts | **696/720 (96.7%)** | **24 (3.3%)** |

Arithmetic left 109 cases unanswered; coding answered every case. A wrong coding answer passed the public tests
but failed hidden tests. [Every baseline and its case outcomes](results/default-baselines-20261128/REPORT.md).

**Swarm versus a single model — 25 November 2026, the same 72 coding cases:**

| System | Solved | Wrong | Unanswered | GPU Wh / solved |
|---|---:|---:|---:|---:|
| **Inkling swarm, R2** | **67/72** | 4 | 1 | **1.33** |
| One DeepSeek V4.1, TP4, one thinking call | 57/72 | 0 | 15 | 2.64 |

The swarm solved more at about half the GPU energy per solved case, with more wrong answers. This is the older
R2 configuration, before the serving upgrade and code_elastic. Models, engines and workflows differ together;
energy is GPU-rail energy, not wall-socket energy. [Comparison and cost scope](results/deepseek-coding3-v1/REPORT.md).

## What the swarm does

Four independent model replicas run candidate attempts. A rejected attempt frees a slot for a replacement;
an accepted answer ends the case and cancels siblings. Scheduling uses capacity and failure counts. The current
policies use generic mechanisms, without task-specific hints or a task-specific search algorithm.

- **Arithmetic — roll12fair:** share free slots across open cases, favouring those with fewer agents in flight;
  escalate after failures and stop on judge acceptance. Exact arithmetic verification scores outcomes separately.
- **Coding — R2 + code_elastic:** keep two agents in flight, replace failures, continue length-cut answers, and
  cancel on the first public-test pass. Hidden tests score the winner; they never select or repair it.

The swarm is **idle by owner decision since 2026-11-27**. These are the retained defaults, not a live-service claim.
[Policy limits and acceptance rules](docs/mechanisms.md) · [Study method and limitations](docs/method.md).

## Adopted levers

Effects below belong to their own measured comparisons; they are not additive.

| Lever | Measured effect against the previous policy | Evidence |
|---|---|---|
| Cancel on accept | Coding 69 vs 66/72; tokens −37%, wall −36% | [early stop](results/coding-earlystop-v1/REPORT.md) |
| Replace failed arithmetic attempts | 90 vs 82/96, 0 wrong; tokens −19%, wall −21% | [escalation](results/swarm-escalate-hard7-v1/REPORT.md) |
| Raise arithmetic cap to twelve | Pooled 173 vs 167/192; four correct late rescues; extra cost disclosed | [replication](results/swarm-cap12-hard14-v1/REPORT.md) |
| Remove strategy hints | Generic 85 vs hinted 83/96, 0 wrong; fewer tokens and Wh/solved | [generic default](results/swarm-generic-hard18-v1/REPORT.md) |
| Widen into free capacity | 87/96 in both arms; wall 0.90x, GPU Wh 0.91x | [widening](results/swarm-wide-hard20-v1/REPORT.md) |
| Water-filling admission | Replication 88 vs 86/96, 0 wrong; wall 0.93x, tokens 0.90x | [roll12fair](results/swarm-fair-hard23-v1/REPORT.md) |
| Coding R2 | Replication 71 vs staggered 68/72; tokens −48%; pooled wrong 2 vs 8 | [R2 replication](results/coding-roll2-v1/REPORT.md) |
| Elastic answer continuation | Replication 70/72, 2 wrong in both; cut-offs 0 vs 12; wall 0.91x | [elastic](results/coding-elastic-v2/REPORT.md) |
| Single-Spark recipe serving | 68 vs 67/72; wall −20%, GPU Wh −20% | [recipe comparison](results/coding-v29-r2-v1/REPORT.md) |

Two tradeoffs matter: water-filling improves batch throughput while increasing per-case latency in batches;
code_elastic raises the per-agent cap by 25%, with every token charged. Its pooled wrong count was 4 vs 3 for plain
R2, within the frozen adoption rule. [Full mechanisms, costs and limits](docs/mechanisms.md).

## What didn't work

| Attempt | Recorded outcome | Details |
|---|---|---|
| Failed-artifact relay | In-swarm 83 vs 84/96; compute +12% despite promising screens | [relay](results/swarm-relay-hard19-v1/REPORT.md) |
| Atom-of-Thoughts | Arithmetic 82 vs 89/96, wall 2.15x; coding 66 vs 68/72 | [arithmetic](results/swarm-aot-hard21-v1/REPORT.md), [coding](results/coding-aot-v1/REPORT.md) |
| Earlier answer reserve | Replication 66/72, 6 wrong vs 71/72, 1 wrong; reverted | [reversal](results/coding-reserve-v2/REPORT.md) |
| Live collaboration board | Corrected screen rescued 8 vs plain continuation 11/41; closed for this protocol | [retest](results/collab-s1-v2/REPORT.md) |
| Differential consensus gate | Wrong 3 vs 5/216, but energy/solved 1.87x; provisional STOP, transports differed | [caveats](docs/results.md#study-42) |

More rejected, parked and untested ideas—and their independent review dispositions—are in
[Mechanisms](docs/mechanisms.md#what-did-not-become-a-default) and the [complete experiment log](docs/results.md).

## Quick start

Replay included traces without GPUs or model credentials:

```sh
git clone https://github.com/knapcio/spark-swarm-lab.git
cd spark-swarm-lab
python3 server.py --runs-dir results/traces --port 18777
```

Open http://127.0.0.1:18777 to inspect proposals, votes and outcomes. These are historical pilot traces.
[Offline tables, figures and evidence archive](REPRODUCING.md).

Inspect a current arithmetic baseline plan without contacting the fleet:

```sh
python3 -m json.tool SWARM_BASELINE_HARD36_PLAN.json
```

For live experiments, [Running](docs/running.md) covers both current study runners, pinned source and admission
requirements, and historical interactive commands. Serving comes from the
[Inkling single-Spark recipe](https://github.com/knapcio/Inkling-2-Mini-1x-DGX-Spark), one replica per node.
The original fleet adapters are environment-specific; the [reproduction guide](REPRODUCING.md) also covers
standalone experiments on your own compatible endpoint.

## Version history

| Date | Default change | Comparison |
|---|---|---|
| 2026-11-26 | roll12fair replaces roll12wide; code_elastic confirmed after reserve revert | [water-filling](results/swarm-fair-hard23-v1/REPORT.md), [elastic](results/coding-elastic-v2/REPORT.md) |
| 2026-11-25 | Work-conserving widening; single-Spark recipe serving | [widening](results/swarm-wide-hard20-v1/REPORT.md), [serving](results/coding-v29-r2-v1/REPORT.md) |
| 2026-11-24 | Generic arithmetic policy replaces strategy hints; R2 replicated | [generic](results/swarm-generic-hard18-v1/REPORT.md), [R2](results/coding-roll2-v1/REPORT.md) |
| 2026-11-23 | Arithmetic cap twelve; coding R2 replaces staggered start | [cap](results/swarm-cap12-hard14-v1/REPORT.md), [R2](results/coding-roll-v1/REPORT.md) |

Every transition, including earlier defaults and the failed reserve adoption: [CHANGELOG.md](CHANGELOG.md).

## Documentation

| File | Contents |
|---|---|
| [Mechanisms](docs/mechanisms.md) | Current policies, measured levers, rejected ideas, historical voting methods |
| [Results](docs/results.md) | Complete experiment chronology, previous-model comparisons, original study evidence |
| [Running](docs/running.md) | Replay, plan inspection, current study runners, historical commands and event format |
| [Method](docs/method.md) | Frozen plans, acceptance vs scoring, replication, accounting and rejection reviews |
| [Reproducing](REPRODUCING.md) | Fresh-checkout analysis, own-endpoint runs, grading limits |
| [Evidence release](EVIDENCE_RELEASE.md) | Published archive, manifests and checksums |
| [Changelog](CHANGELOG.md) | Dated default changes and reversals |

## Credits and licences

Inkling-2-Mini and its original draft head are from Thinking Machines Lab; SGLang supplies the serving runtime.
The adopted serving recipe uses [incoai's DFlash2 drafter](https://huggingface.co/incoai/Inkling-2-Mini-DFlash2).
The experiment log retains the Atom-of-Thoughts credit to Teng et al. and alkimiadev, and the collaboration credit
to blackboard systems and multi-agent debate (Du et al.). [Credits in context](docs/results.md).

Model weights, drafter and serving runtime retain their upstream licences. This checkout has no repository-wide
licence file; this documentation change introduces no new licence.
