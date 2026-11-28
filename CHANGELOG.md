# Changelog

Default changes by date (Europe/Warsaw). Measurements are specific to the linked studies; policies and serving
recipes changed over time. [Current defaults](README.md) · [Complete results](docs/results.md).

## 2026-11-28

- Reorganised the landing page into mechanisms, results, running and method guides; published the complete
  [current-default baseline aggregate](results/default-baselines-20261128/REPORT.md). No default change.
- Retained arithmetic **roll12fair** and coding **R2 + code_elastic + cancel-on-accept**. The swarm is idle by
  owner decision since 2026-11-27. The differential gate remains a provisional STOP; its paired LAN rerun is held.

## 2026-11-27

- No adoptions or reverts from the overnight generic-mechanism screens. Extension failed confirmation, forks
  stopped, restatement was parked, and hold-dispatch failed its energy gate. [Night summary](docs/results.md#study-41).
- Differential gate reduced wrong answers from 5 to 3/216 but used 1.87x GPU Wh per solved case. Verdict provisional
  because transports differed; unchanged variant rejected operationally. [Details](docs/results.md#study-42).

## 2026-11-26

- **roll12fair replaces roll12wide:** water-filling shares slots across open cases. Initial study 82 vs 80/96,
  wall 0.91x; replication 88 vs 86/96, wall 0.93x, 0 wrong throughout. Batch latency tradeoff disclosed.
  [First study](results/swarm-fair-hard22-v1/REPORT.md), [replication](results/swarm-fair-hard23-v1/REPORT.md).
- **code_reserve adopted, then reverted:** initial 71 vs 70/72; replication 66 vs 71/72 with 6 vs 1 wrong.
  Plain R2 restored. [Initial study](results/coding-reserve-v1/REPORT.md), [failed replication](results/coding-reserve-v2/REPORT.md).
- **code_elastic adopted only after replication:** retains the original first-call cap, continues length-cut
  answers, raises total completion cap by 25%. Replication 70/72 and 2 wrong in both arms, wall 0.91x;
  pooled 140/144 with 4 wrong vs 141/144 with 3 wrong. [Retest](results/coding-elastic-v1/REPORT.md),
  [replication](results/coding-elastic-v2/REPORT.md).
- Live collaboration closed for this protocol on Inkling after the corrected replay screen; no live A/B adoption.
  [Retest](results/collab-s1-v2/REPORT.md), [closure](docs/results.md#study-39).

## 2026-11-25

- **roll12wide replaces roll12cancel:** work-conserving widening, 87/96 in both arms; wall 0.90x, GPU Wh 0.91x.
  [Widening study](results/swarm-wide-hard20-v1/REPORT.md).
- **Single-Spark recipe serving replaces the stock cookbook setup:** v2.9 recipe R2 68 vs 67/72, wall and GPU Wh
  each −20%; the retained serving configuration later that day was v2.9.2, recorded in the
  [AoT study](results/swarm-aot-hard21-v1/REPORT.md). [Measured transition](results/coding-v29-r2-v1/REPORT.md).
- Arithmetic and coding Atom-of-Thoughts not adopted; default mechanisms unchanged by those studies.

## 2026-11-24

- **roll12cancel replaces roll12strategy:** task-specific hints removed under the generic-mechanism rule;
  generic 85 vs hinted 83/96, 0 wrong, lower token and energy cost. [Study](results/swarm-generic-hard18-v1/REPORT.md).
- **R2 confirmed:** replication 71 vs staggered 68/72; pooled 142 vs 133/144, wrong 2 vs 8, about half the tokens.
  [Replication](results/coding-roll2-v1/REPORT.md).
- Task-specific partition hints and the stopping-sentence prompt change were excluded from defaults despite
  positive screens. [Historical decisions](docs/results.md).

## 2026-11-23

- **roll12strategy replaces roll8strategy:** cap twelve adopted after replication, owner priority quality first.
  Pooled 173 vs 167/192, 0 wrong, four correct late rescues; higher token and wall cost disclosed.
  [Replication](results/swarm-cap12-hard14-v1/REPORT.md).
- **Coding R2 replaces staggered four-plus-four:** failure-driven replacement, two agents in flight, early stop
  retained; 71 vs 65/72, wrong 1 vs 5, tokens −52%. [Study](results/coding-roll-v1/REPORT.md).
- Loop watchdog provisionally not adopted after review despite passing its original cost gate.
  [Report](results/swarm-loop-hard15-v1/REPORT.md).

## 2026-11-22

- **Coding staggered start replaces all eight at once:** 69/72 in both arms; tokens −16%, wall −13%.
  Early stop retained. [Study](results/coding-stagger-v1/REPORT.md).
- **roll8strategy replaces roll8cancel:** hinted escalation 86 vs 83/96, 0 wrong; 1.60 vs 1.76 Wh per solved case.
  This historical hint policy was later removed. [Study](results/swarm-strategy-hard10-v1/REPORT.md).

## 2026-11-21

- **deep4cancel replaces deep4:** arithmetic cancel-on-accept, 83 vs 86/96, 0 wrong; tokens −33%, wall −36%.
  Owner decision despite missing the frozen non-inferiority margin. [Study](results/swarm-cancel-hard6-v1/REPORT.md).
- **roll8cancel (B+) replaces deep4cancel:** failure-driven escalation to eight; 90 vs deep4 82/96, 0 wrong,
  tokens −19%, wall −21%. [Study](results/swarm-escalate-hard7-v1/REPORT.md).
- **Coding first public-test pass replaces waiting for all agents:** 69 vs 66/72, tokens −37%, wall −36%.
  [Study](results/coding-earlystop-v1/REPORT.md).

## 2026-11-20 / night of 20–21 November

- **Inkling-2-Mini replaces Nemotron** on four independent Spark replicas, through the dialect adapter.
  Initial reruns: arithmetic 90 vs Nemotron swarm 82/96; coding 69 vs 56/72.
  [Initial model comparison and serving record](results/NIGHT_20261121_INKLING.md).

The earlier Nemotron studies, original voting prototype and their unchanged evidence remain in
[Results](docs/results.md#original-study-and-earlier-follow-ups), [Methods](docs/mechanisms.md#historical-interactive-prototype)
and the [published evidence archive](EVIDENCE_RELEASE.md).
