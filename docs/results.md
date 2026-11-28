# Results and experiment history

[Landing page](../README.md) · [Mechanisms](mechanisms.md) · [Method](method.md) · [Changelog](../CHANGELOG.md)

## Current defaults: descriptive baselines

| Domain | Scope | Solved | Wrong | Unanswered |
|---|---|---:|---:|---:|
| Arithmetic, roll12fair | hard-v26 through hard-v36; 11 sets | 947/1,056 | 0 | 109 |
| Coding, R2 + code_elastic | ten baseline cohorts, reused tasks | 696/720 (96.7%) | 24 (3.3%) | 0 |

Arithmetic averages 86.1/96 per set. See the [complete baseline table and per-case export](../results/default-baselines-20261128/REPORT.md), including the valid hard-v33 rerun. These are descriptive checks, not fresh method comparisons. Coding's public tests are acceptance feedback; hidden tests score the selected winner. Passing public tests is not proof of correctness.

## Swarm versus a single model

The [2026-11-25 comparison](../results/deepseek-coding3-v1/REPORT.md) used the same 72 coding cases: R2 solved 67 with 4 wrong and 1 unanswered; one DeepSeek V4.1 TP4 thinking call solved 57 with 0 wrong and 15 unanswered. GPU-rail Wh per solved case: 1.332 versus 2.637. This is the older R2 configuration, before code_elastic and the recipe serving change, not the current baseline. Model, engine and workflow differ together; token accounting also differs (server counters versus client usage).

## Reading the log

The complete Inkling chronology follows, including unsuccessful screens, replication reversals, incidents and report links. Earlier defaults are historical. Current defaults are roll12fair and R2 + code_elastic; the swarm has been idle by owner decision since 2026-11-27. Rejection reviews and the replication rule are indexed in [Method](method.md#rejection-reviews).

## Inkling experiment log

Thinking Machines released Inkling-2-Mini on 2026-11-20 (26.4B total / 3.4B active MoE, the middle 12 of 24 layers
looped three times, native NVFP4 + MXFP8, bundled DSpark draft head). This night: a fast serving recipe for one DGX
Spark, the unchanged Swarm Lab harness pointed at it, and the main experiments rerun with frozen plans.

## Serving ([inkling/TUNING.md](../inkling/TUNING.md))

SGLang `lmsysorg/sglang:inkling-2-mini` with the cookbook DGX Spark DSpark recipe (8 draft tokens), text-only,
128K context, `--mem-fraction-static 0.62`. Per Spark: 51 / 191 / 363 tok/s at 1 / 8 / 24 concurrent thinking requests
(no speculative decoding: 37 / 110 / 222). Two further levers (NV mega-runtime flag, ragged verify with a profiled GB10
cost table) gave nothing. A torch profile shows the step is dominated by weight reads, with the looped core read three
times. A small adapter ([inkling/shim.py](../inkling/shim.py)) gives the harness its vLLM dialect, so no harness code changed.

## Results (same tasks, seeds, budgets, harness and selection rules as the Nemotron runs)

| Task family | One DeepSeek V4.1 | One Nemotron | Nemotron swarm | **One Inkling** | **Inkling swarm** |
|---|---:|---:|---:|---:|---:|
| Hard arithmetic, 96 cases (4 agents + own judge) | 85 | 54 | 82 | 69 | **90** (0 wrong) |
| Hard arithmetic, fresh hard-v5, 96 cases | 76 | | | 61 | **78** (0 wrong) |
| Hard coding, 72 cases (8 agents) | 61 | 37 | 56 | **62** | **69** |
| Bug fixing, whole project in context, 36 | 36 | 26 | 35 | **36** | 36 |

- [Fresh replication](../results/inkling-hard5-v1/REPORT.md) on arithmetic-hard-v5 (plans frozen before the corpus existed): swarm 78 vs DeepSeek 76 (+8/-6).
  Pre-registered pooled test over 192 cases: 168 vs 161, +14/-7 (p = 0.19), 0 wrong; One Inkling 130 is clearly below DeepSeek (p = 3e-6).
  So the swarm matches DeepSeek, it does not beat it significantly.
- Arithmetic hard-v4 swarm vs DeepSeek paired +6/-1 (p = 0.125); vs Nemotron swarm +9/-1 (p = 0.02). Judge: 0 false accepts in 330.
- Coding swarm vs DeepSeek +10/-2 (p = 0.039); One Inkling vs DeepSeek +8/-6 (p = 0.79).
- [Executable disproofs](../results/disproof-selection-v1/REPORT.md) (independent review idea #1): contracts written from the public task alone
  are the best arbiter-free code selector so far: Nemotron candidates 56 -> 59 (judge 57, output vote 55; oracle 64),
  Inkling candidates 69 -> 70 (oracle 71).

## Does it pay now? ([efficiency-v1](../results/efficiency-v1/REPORT.md), independent review idea #6)

Same four Sparks, GPU-rail energy from 1 Hz `nvidia-smi`: the Inkling fleet (four replicas) produces 1,412 tok/s at
0.083 J/token; DeepSeek TP4 at its 16 slots 276 tok/s at 0.44 J/token. Per solved task, One Inkling solves ~5x more coding
tasks per hour than One DeepSeek at ~1/5 of the GPU energy (equal accuracy), and is cheaper on bugs and arithmetic too.
The Inkling swarm is the most accurate system and costs more energy per solved task than One DeepSeek.

## Day 2026-11-21: cancel the other agents once one plan is accepted ([swarm-cancel-hard6-v1](../results/swarm-cancel-hard6-v1/REPORT.md))

Frozen plan (2376372) before a fresh corpus (arithmetic-hard-v6, d8bc18e); three arms run alone on the fleet, 96 paired
cases each, server-side token counting (includes aborted requests), GPU-rail energy.

| Arm | Solved | Wrong | Server tokens/case | Arm wall | GPU energy per solved case |
|---|---:|---:|---:|---:|---:|
| A deep4 (all 4 agents to the end) | 86 | 0 | 66.3K | 87 min | 1.92 Wh |
| **B deep4cancel** (first accepted plan ends the case) | 83 | 0 | **44.6K (-33 %)** | **56 min (-36 %)** | **1.30 Wh** |
| C waves of 2 with cancel | 81 | 0 | 39.3K (-41 %) | 59 min (-32 %) | 1.32 Wh |

B missed the frozen non-inferiority margin (>= 84) by one case, but every one of its 4 losses was a case where it
cancelled nothing (it ran A's policy and drew worse samples); where it cancelled, the answer was already accepted by a
judge with 0 false accepts. Same-seed agents changed outcome in 18 % of pairs between the two runs, so a 3-case gap
between identical policies is ordinary. **deep4cancel is now the default arithmetic swarm policy** (owner decision).
The shim now treats client disconnects as cancellations (`shim:client_cancels`; SGLang aborts in < 0.5 s).
Offline, the same early stop on the coding swarm would keep 69/72 (not the disproof 70) for about a third fewer tokens.
[One DeepSeek on the same hard-v6 tasks](../results/swarm-cancel-hard6-v1/DEEPSEEK.md): 85/96 (swarm A 86, paired +3/-2) at 1.29 Wh per
solved case, the same as swarm B (1.30). Exploratory pooled v4+v5+v6 (288): swarm 254 vs DeepSeek 246 (+17/-9, p = 0.17).

## Day 2026-11-21 (2): escalation, B+ ([swarm-escalate-hard7-v1](../results/swarm-escalate-hard7-v1/REPORT.md))

Frozen plan (1409067) before a fresh corpus (arithmetic-hard-v7, 168e423). B+ = cancel-on-accept plus adaptive escalation:
each agent that ends without an accepted plan is replaced at once by a fresh-seed agent, up to 8 per case.

| Arm | Solved | Wrong | Server tokens/case | Arm wall | GPU energy per solved case |
|---|---:|---:|---:|---:|---:|
| B deep4cancel | 79 | 0 | 44.0K | 55 min | 1.31 Wh |
| **B+ roll8cancel** | **90** | 0 | 53.6K | 71 min | 1.48 Wh |
| A deep4 (reference) | 82 | 0 | 66.6K | 90 min | 2.04 Wh |

B+ vs A +9/-1 (p = 0.02) at -19 % tokens and -21 % wall; 6 strict rescues (cases every one of the first four agents had
failed). **B+ is now the default arithmetic swarm policy.** B vs A was -3 on both fresh corpora (pooled +6/-12, p = 0.24);
every one of those losses was a case where B cancelled nothing, so it is generation noise by mechanism, noted openly.
[One DeepSeek on the same hard-v7 tasks](../results/swarm-escalate-hard7-v1/DEEPSEEK.md): 79/96. **B+ vs One DeepSeek 90 vs 79, paired
+13/-2 (p = 0.007)**, 0 wrong, at 1.48 vs 1.66 Wh per solved case on the same four Sparks: the first significant win of
the swarm over DeepSeek. Hybrid (DeepSeek only on B+'s 6 abstentions): 92/96.

## Day 2026-11-21 (3): coding swarm early stop, live ([coding-earlystop-v1](../results/coding-earlystop-v1/REPORT.md))

Frozen plans (669665e) before any call with fresh seeds 4-6 on coding-hard-v1 (72 cases, 8 agents of 32K).

| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy per solved case |
|---|---:|---:|---:|---:|
| F: all 8 agents to the end, slot-order first passing | 66 | 99.8K | 96 min | 2.74 Wh |
| **E: first proposal passing the public tests ends the case** | **69** | **62.8K (-37 %)** | **61 min (-36 %)** | **1.69 Wh** |

On the same proposals (inside F), the first passing proposal in time is the better pick than the first in slot order
(71 vs 66). **Early stop is now the default for the coding swarm.** Serving changed before this study (owner): Inkling
runs with `--mem-fraction-static 0.75` (KV ~1.08M tokens per node; MemAvailable >= 24.3 GiB under full load).

## Night 2026-11-21 (4): escalate earlier and further? ([swarm-burst-hard8-v1](../results/swarm-burst-hard8-v1/REPORT.md))

Fresh hard-v8 (plan 4eb69e7 frozen first). B+ (default) 91/96 at 47.3K tokens/case, 66 min, 1.36 Wh per solved case;
B++ (cap 12 + 900 s burst to 8 in flight) 90/96 at 70.7K, 91 min, 1.94 Wh. Agents 9-12 rescued 4 cases, but the time
trigger fired 21 times (9 needlessly) and the burst agents slowed every other case. **B+ stays the default.**

## Night 2026-11-22 (5): coding swarm, start 4 agents and add 4 only if needed ([coding-stagger-v1](../results/coding-stagger-v1/REPORT.md))

Fresh seeds 7-9 on coding-hard-v1 (plans ec69a43 frozen first), both arms with early stop. All 8 agents at once: 69/72,
59.8K tokens/case, 60 min, 1.66 Wh per solved case. Staggered (4 first, 4 more after 300 s or when the first four fail):
**69/72, 50.0K tokens/case (-16 %), 52 min (-13 %), 1.42 Wh**; the second wave was needed in 39 of 72 cases.
**Coding default is now early stop + staggered start.**

## Night 2026-11-22 (6): escalation agents that see the judge's critique ([swarm-repair-hard9-v1](../results/swarm-repair-hard9-v1/REPORT.md))

Fresh hard-v9 (plan 8b28aed frozen first; a harder corpus). B+ 86/96 (0 wrong, 69.1K tokens/case); escalation agents
given every rejected plan with the judge's reason: 83/96, and their success rate halved (4/73 vs 9/82 accepted;
4 vs 8 strict rescues). Feedback anchors the agents. **B+ (fresh escalation agents) stays the default.**
[One DeepSeek on hard-v9](../results/swarm-repair-hard9-v1/DEEPSEEK.md): 77/96; B+ 86 (+12/-3, p = 0.035). **Pre-registered pooled
hard-v7 + v9: B+ 176 vs One DeepSeek 156 of 192, paired +25/-5 (p = 0.0003), 0 wrong**: the swarm's lead over DeepSeek
replicates on fresh tasks. Hybrid (DeepSeek only on B+ abstentions): 181/192.

## Cost of the policies measured 2026-11-21/22 ([energy-defaults-20261122](../results/energy-defaults-20261122/tables.md))

Each arm ran alone on the four Sparks; GPU-rail energy from the 1 Hz logs (CPU, memory, NIC, fans not included).

| Corpus | Policy | Cases | Solved | Server tokens/case | Wall | GPU Wh | Wh per solved | Cases per hour |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| arithmetic-hard-v6 | deep4 | 96 | 86 | 66,267 | 87 min | 165.0 | 1.92 | 66 |
| arithmetic-hard-v6 | deep4cancel | 96 | 83 | 44,633 | 56 min | 108.0 | 1.30 | 102 |
| arithmetic-hard-v6 | waves2cancel | 96 | 81 | 39,250 | 59 min | 106.8 | 1.32 | 97 |
| arithmetic-hard-v7 | deep4 | 96 | 82 | 66,592 | 90 min | 167.1 | 2.04 | 64 |
| arithmetic-hard-v7 | deep4cancel | 96 | 79 | 43,976 | 55 min | 103.7 | 1.31 | 105 |
| arithmetic-hard-v7 | roll8cancel | 96 | 90 | 53,641 | 71 min | 133.4 | 1.48 | 81 |
| arithmetic-hard-v8 | roll8cancel | 96 | 91 | 47,278 | 66 min | 123.7 | 1.36 | 87 |
| arithmetic-hard-v8 | roll12burst | 96 | 90 | 70,657 | 91 min | 174.7 | 1.94 | 63 |
| arithmetic-hard-v9 | roll8cancel | 96 | 86 | 69,107 | 88 min | 167.9 | 1.95 | 65 |
| arithmetic-hard-v9 | roll8repair | 96 | 83 | 69,950 | 87 min | 166.8 | 2.01 | 66 |
| coding-hard-v1 s4-6 | all 8 to the end | 72 | 66 | 99,752 | 96 min | 180.7 | 2.74 | 45 |
| coding-hard-v1 s4-6 | early stop | 72 | 69 | 62,790 | 61 min | 116.6 | 1.69 | 70 |
| coding-hard-v1 s7-9 | early stop | 72 | 69 | 59,849 | 60 min | 114.5 | 1.66 | 72 |
| coding-hard-v1 s7-9 | early stop + stagger | 72 | 69 | 50,019 | 52 min | 98.2 | 1.42 | 83 |
| arithmetic-hard-v6 | One DeepSeek (TP4, reference) | 96 | 85 | 6,442 | 54 min | 110.0 | 1.29 | 107 |
| arithmetic-hard-v7 | One DeepSeek (TP4, reference) | 96 | 79 | 8,146 | 65 min | 131.4 | 1.66 | 89 |

Defaults since this work: arithmetic **B+ roll8cancel** (cancel on accept + failure-driven escalation to 8 agents),
coding **early stop + staggered start**. Per solved case they cost about 1.4-1.95 Wh (arithmetic, depending on corpus
hardness) and 1.4 Wh (coding), against 1.9-2.0 Wh (deep4) and 2.7 Wh (all 8 coding agents to the end) before;
One DeepSeek costs 1.3-1.8 Wh per solved case on the same fleet and solves fewer of these tasks.

## Morning 2026-11-22 (7): escalation agents with distinct strategy hints ([swarm-strategy-hard10-v1](../results/swarm-strategy-hard10-v1/REPORT.md))

Fresh hard-v10 (plan 37b82fc frozen first). B+ 83/96 (58.3K tokens/case, 1.76 Wh per solved case); escalation agents
with one of four task-agnostic strategy hints each: **86/96, 0 wrong, 55.4K tokens/case, 1.60 Wh**, escalation success
5/60 vs 2/65 accepted, 4 vs 1 strict rescues (small counts; paired +5/-2). Frozen rule met: **roll8strategy is the new
arithmetic default** (B+ plus diverse escalation). Diversity helps where critique (hard9) hurt.

## Day 2026-11-22 (8): three agents in flight instead of four ([swarm-width3-hard11-v1](../results/swarm-width3-hard11-v1/REPORT.md))

Fresh hard-v11 (plan a320690 frozen first). Default roll8strategy (4 in flight) 83/96, 61.2K tokens/case, 79 min; 3 in
flight 81/96 with **+17 % tokens**, +44 % wall, +37 % energy: fewer racers mean a later first accept (cancelled agents ran
longer) and more escalations. **4 in flight stays.** (Caveat: the 3-wide arm also used only ~15 agents per node.)

Prefix cache (from the server counters of every arm today): the SGLang radix cache already serves 94-97 % of the
arithmetic prompt tokens and 65-74 % of the coding prompt tokens; the prefill that is still computed is 2-3 % of the
generated tokens. Routing a case's agents to one node could save at most the 3 extra computations of one ~500-token
prompt per case, well under 1 % of the work, so no fleet study was spent on it.

## Day 2026-11-22 (9): escalation cap 12 instead of 8 ([swarm-cap12-hard12-v1](../results/swarm-cap12-hard12-v1/REPORT.md))

Fresh hard-v12 (plan 0a475c3 frozen first). Default roll8strategy 81/96 (62.0K tokens/case, 79 min); cap 12 85/96, 0 wrong,
2 cases answered only by agents 9-12, paired +6/-2 (p = 0.29), 2.28 vs 1.85 Wh per solved case; +24 % tokens and +29 % wall
(my frozen limits were 20 % / 25 %). **Cap 12 = max-accuracy mode**; cap 8 stays the efficiency default until a
replication on a fresh corpus (queued next) shows whether the gain holds.

## Day 2026-11-22 (10): arithmetic and coding swarms at the same time ([mixed-task-v1](../results/mixed-task-v1/REPORT.md))

Both defaults on fresh work (arithmetic-hard-v13, coding seeds 10-12), plans a717252 frozen first. Together (10 + 10
requests per node): 141 min, 267 Wh, arithmetic 86/96 (0 wrong), coding 67/72. One after the other (20 per node each):
124 min, 238 Wh, 88/96 and 65/72. **Run them one after the other**: the static split leaves half the fleet idle once the
shorter workload ends; accuracy is the same within noise.

## Night 2026-11-22/23 (11): cap 12 replicated ([swarm-cap12-hard14-v1](../results/swarm-cap12-hard14-v1/REPORT.md))

Fresh hard-v14 (plan 0de332a frozen first). Cap 12 88/96 vs cap 8 86/96, 0 wrong, 2 cases answered only by agents 9-12;
pre-registered pooled hard-v12 + v14: 173 vs 167 of 192 (+9/-3, p = 0.15), 4 noise-free late rescues, 0 wrong. Cost:
+17 % tokens and +25 % wall on hard-v14 (1.96 vs 1.65 Wh per solved case), paid only on cases 8 agents cannot solve.
**roll12strategy (cap 12) is now the arithmetic default** (owner: quality first).

## 2026-11-23 (12): coding failure-driven replacement ([coding-roll-v1](../results/coding-roll-v1/REPORT.md))

independent review idea 1, plans 205783b frozen before seeds 13-15. Early stop in every arm. S (stagger 4+4 at 300 s, old default)
65/72, 5 wrong (public tests pass, hidden fail); R4 (replace failures, 4 in flight) 69, 2 wrong, -25 % tokens; R2 (2 in
flight) 71, 1 wrong, -52 % tokens, 1.01 vs 1.52 Wh per solved, R2 vs S +6/-0 (p = 0.031); a pool replay puts R2 at
about 69 solved, so part of the +6 is seed luck. **R2 is the coding default** (not worse, half the tokens).

## 2026-11-23 (13): loop watchdog ([swarm-loop-hard15-v1](../results/swarm-loop-hard15-v1/REPORT.md))

independent review idea 3, plans 9ffceec before hard-v15 (6919fe4). D (roll12strategy) 85/96 vs L (+ zlib loop watchdog) 83/96, 0 wrong
in both; 102 streams stopped, 0 of their forced answers accepted. Frozen rule: adopt (L/D tokens 0.918, partly a D-side
infra waste). Replay: 9 of 708 streams that met the criterion still gave their case's correct answer, 8 of them via a
forced answer at the thinking-budget limit (independent review review: not proven loop escapes; a 54-check trigger would spare all 9).
**Watchdog provisionally not adopted** (quality first); fair follow-up: none vs forced answer vs a "change approach" nudge.

## 2026-11-23 (14): table relay prototype screen (not a study)

24 development six-number cases: 0 solved, 0 wrong; builder tables covered 0.07 % of reachable values and 92 % of kept
rows were false. independent review review: the screen was unfair to the idea (all 360 builders hit the 1,600-token thinking cap and
answered only after forced closure; ~147 rows per group). **This prototype is rejected; the idea stays open** for a fair
re-screen (worked examples, one group per builder, calibrated budgets, direct answer vs thinking).

## 2026-11-23/24 (15): escalation hints on a shared first wave ([swarm-hints-hard16-v1](../results/swarm-hints-hard16-v1/REPORT.md))

independent review ideas 4 + 5. One default first wave on 192 six-number cases of fresh hard-v16 (144 solved, 0 wrong), then four
escalation-only arms on the 48 strict-hard cases, same seeds, only the hint text differs. Rescued: no hints 19, current
hints 14, hints 0+2 16, **last-move partition hints 31** (+18/-1 vs current, p = 7.6e-5), 0 wrong in every arm, P with
23 % fewer tokens per case. The current hints show no benefit. **Owner rule (2026-11-24): generic swarm only, so P is not
adopted and its confirmation was cancelled** (all hints here are arithmetic-specific).

## 2026-11-24 (16): round 3 on hard-v17 ([swarm-round3-hard17-v1](../results/swarm-round3-hard17-v1/REPORT.md))

Worker with one retry on upstream transport loss and judge retry in every arm. D (default) 87/96, L (prompt sentence
"unused numbers are allowed; stop as soon as the target appears") 88/96, 0 wrong both; L passed its frozen rule but is a
task-specific prompt change: **not adopted (owner rule)**. Add-on X, slots 12-19 on D's 9 abstentions: 2 rescued, 0 wrong,
+28 % of D's tokens: **more agents is a generic mechanism; cap 20 passes, live load-gated version next**. Recall pass:
dev screen 0/30 (262 plans, none correct), task-specific anyway. Closers: task-specific as implemented (arithmetic wanted
list), not run on hard-v17.

## Proposal: a generic default without hints

The owner rule also covers the escalation strategy hints in today's default `roll12strategy`. Existing data says they
buy nothing: hard-v10 (cap 8) hints vs none +5/-2 (p = 0.45); hard-v16 strict-hard cases no hints 19 vs strategy hints 14
rescues (+10/-5 for no hints, p = 0.30) at equal tokens; independent review's pooled replay unhinted 19/53 vs hinted 11/55 rescues.
Proposed default: `roll12cancel` (cap 12, failure-driven replacement, cancel on accept, no hints). Confirmation planned on
a fresh corpus together with the live idle-capacity escalation: roll12strategy vs roll12cancel vs roll12idle.

<a id="study-17"></a>

## 2026-11-24 (17): generic default and idle-capacity escalation ([swarm-generic-hard18-v1](../results/swarm-generic-hard18-v1/REPORT.md))

Owner rule: generic swarm only. Fresh hard-v18, plan 98a267a frozen first, each arm alone, 0 wrong in every arm.
S roll12strategy (old default, task-specific hints) 83/96; **G roll12cancel (same policy, no hints) 85/96** (+4/-2), fewer
tokens and Wh per solved: **G is the new arithmetic default** (frozen rule passed). GI roll12idle (G plus up to 8 extra
unhinted agents per failed case while a node holds < 12 requests) 86/96, 1 case answered by slots 12-19, but arm wall
1.24 x G (gate 1.10) and +25 % tokens: not adopted.

<a id="study-18"></a>

## 2026-11-24 (18): coding R2 replicated ([coding-roll2-v1](../results/coding-roll2-v1/REPORT.md))

Fresh seeds 16-18: R2 71 vs S 68 of 72 (+4/-1), wrong 1 vs 3, -48 % tokens. Pooled over both studies R2 142 vs S 133 of
144, wrong 2 vs 8. **R2 stays the coding default.** Next running: coding-roll3-v1, R2 vs R1 (one agent in flight).

<a id="study-19"></a>

## 2026-11-24 (19): coding R1 ([coding-roll3-v1](../results/coding-roll3-v1/REPORT.md))

Seeds 19-21: R1 (one agent in flight) 66 vs R2 67 of 72, wrong 6 vs 4, -33 % tokens, +30 % wall: **R2 stays**.

<a id="study-20"></a>

## 2026-11-24 (20): generic artifact relay, dev screen ([relay-screen-hard18-v1](../results/relay-screen-hard18-v1/REPORT.md))

independent review's fair generic closer test. On 14 deduplicated generic abstentions of hard-v18 (7 puzzles), up to 4 uniformly sampled
failed-agent artifacts (last 12,000 characters) went to new workers with one fixed sentence ("Another solver worked on this
exact task ... use whatever is correct in it, finish the task"), against the same number of fresh equal-budget workers:
**RELAY 4 vs REPLACE 0 rescues**, 0 wrong in both, generation tokens -8 % but total compute +17 % (the artifacts are prompt
input). Gate passed; a replication on 29 unhinted esc_none abstentions of hard-v16 is running, then an in-swarm study
(roll12relay: escalation agents receive one failed artifact) on a fresh corpus.

<a id="study-21"></a>

## 2026-11-24 (21): artifact relay replicated ([relay-screen-hard16-v1](../results/relay-screen-hard16-v1/REPORT.md))

29 unhinted esc_none abstentions of hard-v16 (6 puzzles), plan 80c6f4f frozen first: **RELAY 5 vs REPLACE 2 rescues**
(relay-only 4, replace-only 1), 0 wrong; total compute +21 % (artifacts are prompt input). Pooled over both screens
RELAY 9 vs REPLACE 2 of 43, 0 wrong: the pre-registered gate for the in-swarm study passed; swarm-relay-hard19-v1
(roll12cancel vs roll12relay, plan 7ee58f6, corpus 61ca1bf) started 18:40Z.

## 2026-11-24/25 night (22-25): generic mechanisms

- **Relay in the swarm** ([swarm-relay-hard19-v1](../results/swarm-relay-hard19-v1/REPORT.md)): roll12cancel 84 vs roll12relay 83 of 96, 0 wrong,
  +12 % total compute: **not adopted** (the screen rescues did not turn into extra solves inside the swarm); to independent review review.
- **Work-conserving widening** ([swarm-wide-hard20-v1](../results/swarm-wide-hard20-v1/REPORT.md)): roll12cancel 87 vs roll12wide 87, 0 wrong,
  wall 0.90x, GPU Wh 0.91x, tokens +1 %: **roll12wide is the new arithmetic default** (generic; same answers, less wall and energy).
- **Dense relay window** ([relay-window-v1](../results/relay-window-v1/REPORT.md)): dense 1 vs tail 1 of 38: tail stays (moot without relay).
- **Judge replays** ([judge-replay-v1](../results/judge-replay-v1/REPORT.md)): a generic coding judge as a second key would reject 20/31 wrong
  winners but also 61/684 correct (8.9 % > 5 % cap): not pursued; a second arithmetic judge on forced answers found 0 false
  accepts in 2,787 invalid forced plans and rejected 0 of 54 valid ones: nothing to gain. Rejections to independent review review.

<a id="study-26"></a>

## 2026-11-25 (26): One DeepSeek on the coding-roll3 cases ([deepseek-coding3-v1](../results/deepseek-coding3-v1/REPORT.md))

Owner OK; plan 11fd27d frozen before any call. Native DeepSeek V4.1 TP4, one thinking call per case, same 72 cases:
DeepSeek 57/72 (0 wrong, 15 unanswered) vs swarm R2 67/72 (4 wrong) and R1 66/72 (6 wrong). Paired: swarm R2 +11/-1
(p = 0.006), R1 +13/-4 (p = 0.049). Hybrid R2 + DeepSeek on R2's 1 unanswered case: 67/72. Wh per solved: DeepSeek 2.64,
R2 1.33, R1 1.32. DeepSeek never answered wrong but left 21 % unanswered; the swarm answers almost everything at half the
energy per solved case, with 4-6 wrong answers that pass the public tests.

<a id="study-27"></a>

## 2026-11-25 (27): generic Atom-of-Thoughts decomposition ([swarm-aot-hard21-v1](../results/swarm-aot-hard21-v1/REPORT.md))

Owner-approved (Teng et al. 2025, arXiv 2502.12018; taskgraph idea credited to alkimiadev). Fresh hard-v21, plans 58257fb,
v2.9.2 recipe serving, roll12wide in both arms, same 32,768-token budget per agent. Plain 89/96 vs AoT 82/96, 0 wrong
in both; plain-only 7, AoT-only 0 (p = 0.016); AoT 2.1x server tokens, 2.15x wall, 3.46 vs 1.50 Wh per solved. Nearly
every AoT agent decomposed and contracted (326/333); the split budget leaves the final solve only 16K of thinking,
which these hard search tasks need in one stream. **AoT not adopted** (rejection to independent review review); coding AoT running.

<a id="study-28"></a>

## 2026-11-25 (28): AoT on coding ([coding-aot-v1](../results/coding-aot-v1/REPORT.md))

code_aot 66/72 vs plain code_xl 68/72 (AoT-only 3, plain-only 5, p = 0.73), 3 vs 4 wrong, 3 unanswered, 2.5x tokens,
1.78 vs 0.64 Wh per solved: **not adopted** (with arithmetic AoT, both rejections go to independent review).

<a id="study-29"></a>

## 2026-11-25 (29): coding without provided tests ([coding-notests-v1](../results/coding-notests-v1/tables.md))

Owner question: what does the swarm lose without given tests? Same 72 fresh cases, scored on all hidden tests. Public
tests (default) 69/72, 3 wrong; no tests + Inkling judge acceptance (16,384-token judge) 70/72, 2 wrong; no tests + the
agents' own tests 68/72, 1 wrong, 3 unanswered. **No measurable accuracy loss** (paired +3/-2 and +3/-4, p = 1), but about
2x wall and 2.2x energy per solved case (0.77 -> 1.65-1.72 Wh). Even at 16,384 thinking tokens 51 % of judge verdicts
were forced after the cap.

<a id="study-30"></a>

## 2026-11-26 (30): water-filling admission ([swarm-fair-hard22-v1](../results/swarm-fair-hard22-v1/REPORT.md))

roll12fair (every case open from the start; a free agent slot goes to the case with the fewest agents in flight, at
most 4 before a case's first failure and 8 after, cap 12) vs roll12wide on 96 fresh hard-v22 cases: 82 vs 80 solved,
0 wrong in both, F-only 5 / W-only 3 (p = 0.73); arm wall 0.91x, server tokens 0.90x, energy 0.91x (2.06 vs 2.32 Wh
per solved). Frozen rule met: **roll12fair replaces roll12wide**. Cost: the time to an answer per case rises (median
475 s vs 218 s from case start), because cases share the slots instead of being served one batch at a time; the gain
is batch throughput, not single-case latency. Idea: the recorded idea notes idea 2.

<a id="study-31"></a>

## 2026-11-26 (31): elastic answer reserve in coding ([coding-reserve-v1](../results/coding-reserve-v1/REPORT.md))

Replay screen of 116 recorded cut-off coding agents (19 N rows rerun after the multi-token end-of-thinking fix,
merged under the same frozen gate): E 89 / N 85 feedback passes, both qualify, N preferred (>= 90 % of E) ->
code_reserve (an answer cut by length continues in the same sequence in 2,048-token steps, at most 10,240 answer
tokens; thinking cap 26,624 of the 32,768 budget). Study on seeds 28-30 (72 cases): R2 + reserve 71/72, 1 wrong vs R2
70/72, 2 wrong (reserve-only 1, plain-only 0, p = 1); 0 cut-off answers vs 5; tokens 0.82x, wall 0.67x, 0.52 vs 0.74 Wh
per solved. Frozen rule met: code_reserve was adopted, **then reverted** after the failed replication below. Idea: the recorded idea notes idea 1.

<a id="study-32"></a>

## 2026-11-26 (32): reserve replication FAILED, adoption reverted ([coding-reserve-v2](../results/coding-reserve-v2/REPORT.md))

Same plans and rule on fresh seeds 31-33: R2 + reserve 66/72, **6 wrong** vs R2 71/72, 1 wrong (plain-only 5, reserve-only 0,
p = 0.06). Pooled v1+v2: 137 / 7 wrong vs 141 / 3. I adopted code_reserve on a +1 case that the replication reversed;
**the coding default is plain R2 again**. Investigation: the arms also differ in the first-call thinking cap (26,624 vs
30,720), but five of the six wrong answers closed their own thinking below either cap. Same-seed agents diverge within
about 60 characters on this serving, so the arms are independent samples; the same slot won in all five flipped cases,
and paired thinking length is unchanged (p = 0.19). No mechanism found beyond sampling variance, plus one answer forced
at the lower cap (independent review: pairing by task stays valid; selection effects are not excluded; RETEST code_elastic, which keeps
the 30,720 cap, is queued as coding-elastic-v1 on seeds 37-39). Lesson: a single-study adoption that wins on efficiency at +1 quality needs its replication before it
becomes the default.

<a id="study-33"></a>

## 2026-11-26 (33): water-filling replicated ([swarm-fair-hard23-v1](../results/swarm-fair-hard23-v1/REPORT.md))

Same plan and rule on fresh hard-v23: roll12fair 88 vs roll12wide 86, 0 wrong in both (F-only 4, W-only 2, p = 0.69);
wall 0.93x, tokens 0.90x, energy 0.93x. Pooled with hard-v22: 170 vs 166 of 192, 0 wrong. **roll12fair stays the
arithmetic default for batch runs.** The per-case latency cost (median time to an answer 567 s vs 300 s) appears only in
batches; single-task use is unaffected by construction (same 4 / 8 / 12 limits, nothing to share), not measured.

<a id="study-34"></a>

## 2026-11-26 (34): elastic answer reserve, retest ([coding-elastic-v1](../results/coding-elastic-v1/REPORT.md))

independent review's RETEST after the failed code_reserve replication: code_elastic keeps code_xl's 30,720-token first call and only
continues length-cut answers (total <= 40,960, all charged). Seeds 37-39: 70/72, 2 wrong vs plain R2 71/72, 1 wrong
(p = 1); 0 cut-off answers vs 5; tokens 0.93x, wall 0.69x, 0.63 vs 0.78 Wh per solved. The frozen rule is met at its
margins; **not the default until a replication passes** (queued behind the collaboration screens). One infrastructure
stop of arm P (a single server disconnect, no retry in this worker) was rerun in full and is disclosed in the report.

<a id="study-35"></a>

## 2026-11-26 (35): elastic answer reserve replicated ([coding-elastic-v2](../results/coding-elastic-v2/REPORT.md))

Same plans and rule on fresh seeds 40-42: 70/72, 2 wrong in both arms (p = 1); 0 cut-off answers vs 12; tokens 0.90x,
wall 0.91x, 0.83 vs 0.94 Wh per solved. Pooled v1+v2: 140 / 4 wrong vs 141 / 3 of 144. Passed twice:
**code_elastic becomes the coding default** (25 % higher per-agent cap, every token charged; disclosed).

<a id="study-36"></a>

## 2026-11-26 (36): live collaboration, screen S0 ([collab-s0-v1](../results/collab-s0-v1/REPORT.md), [collab-s0-v2](../results/collab-s0-v2/REPORT.md))

The owner's swarm idea (agents share findings on a board while they work; design the recorded live-collaboration design, credit
blackboard systems and multi-agent debate, Du et al. 2023). S0 is the frozen plumbing and note-quality screen on 100
recorded checkpoints. v1: plumbing exact (prefix and turn boundaries 1.0) but STOP; independent review found the arithmetic gate a
checker artifact (all 12 flagged equations were correct) and the cache gate unreachable without a board budget. On the
owner's direction the notes became facts only, and every statement is checked before posting (exact arithmetic,
public cases for code, otherwise a short checker turn on the solver's own context; tags VERIFIED / agent-checked /
UNVERIFIED). v2: all gates pass (cached 0.966, notes within 256 tokens 1.0, posted arithmetic 80 evaluable / 0 false,
coverage 0.90) except checkpoint latency 23.5 s: each note waited behind the other streams' replay warm-up prefill
(note first token 21 s vs 2.5 s for the continuation). v3 (a wave's warm-ups complete before its notes, thresholds
unchanged): **PASS** on every gate ([collab-s0-v3](../results/collab-s0-v3/REPORT.md)): checkpoint latency 3.1 s, cached 0.967,
posted arithmetic 89 evaluable / 0 false, coverage 0.95, focus 0.98. Weak spot: 137 of 300 statements were dropped as
malformed tried/checked lines (not a gate). Next: S1, the decisive replay screen.

<a id="study-37"></a>

## 2026-11-26 (37): live collaboration, decisive replay screen S1 ([collab-s1-v1](../results/collab-s1-v1/REPORT.md))

41 recorded all-fail puzzles (every agent past 8,192 tokens, none accepted), continued from their recorded prefixes in
three arms: D' plain continuation, C' the frozen protocol (facts-only notes, statements checked before posting, a
budgeted board read at each checkpoint), C'div the same plus the separate division-of-work sentence (owner decision).
Frozen gate per protocol arm: 0 wrong, rescued puzzles >= D' + 7 (familywise false pass <= 0.095), accepted agents
>= D', novelty >= D' - 0.02. Result, 0 wrong in every arm: D' 6 rescued, C' 5 (lead -1; novelty 0.945 vs 0.966, i.e.
below the allowed drop), C'div 9 (lead +3; protocol-only 7, plain-only 4, p = 0.55). **Both STOP; no A/B.** The
division sentence is the only signal (+3, not significant); sharing notes alone slightly lowered novelty, the herding
risk the design named. Peak load 20 per node, drain confirmed. Reviews of the rejection follow (independent review).

<a id="study-38"></a>

## 2026-11-26 (38): live collaboration, S1 retest ([collab-s1-v2](../results/collab-s1-v2/REPORT.md))

independent review found a protocol defect in S1 v1: 247 of 275 forced answer calls of the protocol arms returned "Paused." instead of
an answer. v2 fixes it (an explicit answer-only user turn at the end, in both arms for parity, thinking off, inside the
2,048-token reserve; 0 of 264 forced calls now return "Paused."), accepts the tried-statements that only lack their label
(lossless), and runs D' against C'div only (plain C' dropped). Gates and margins unchanged. Result, 0 wrong in both arms:
**D' 11 rescued, C'div 8 of 41 (lead -3; protocol-only 6, plain-only 9, p = 0.61): STOP.** The answer-turn fix raised the
plain control from 6 to 11 and left the protocol at 8 to 9, so v1's +3 was mostly the control's missing answer turn. With a fair terminal turn, sharing facts on a board does not rescue more all-fail
puzzles than independent continuation; novelty is again lower (0.938 vs 0.957). The A/B does not run. Peak load 20 per
node (driver), 17 measured, drain confirmed.

<a id="study-39"></a>

## 2026-11-26 (39): live collaboration CLOSED for Inkling-2-Mini

The owner's swarm idea, agents that share findings while they work, was built as a generic protocol (design
the recorded live-collaboration design; credit blackboard systems and multi-agent debate, Du et al. 2023) and screened under frozen
rules. It is closed for this model on these tasks (independent review: DEAD for this live-board program; not a claim that every
collaboration design fails).

What worked:
- **Verification before posting:** exact arithmetic checking, public cases for code, and a short checker turn on the
  solver's own context kept every posted arithmetic statement correct (S0 v3: 89 evaluable, 0 false) and every arm at
  **0 wrong** across S1 v1 and v2.
- **Plumbing:** prefix-exact replays, turn composition verified against the server's template on every node, cached
  checkpoints (0.967), 3.1 s checkpoint latency; fleet lease, abort confirmation per request and fenced drain held load
  at or below 20 per node.
- **The terminal fix:** an explicit answer-only turn ended the "Paused." contamination (247 of 275 forced calls in v1;
  0 of 264 in v2).

What failed:
- **No rescue gain:** with a fair ending in both arms the plain control rescued 11 of 41 all-fail puzzles and the
  protocol 8 (v1's +3 for C'div was mostly the control's missing answer turn; the fix gave the control +5).
- **Herding:** novelty fell in every protocol arm (0.938-0.945 vs 0.957-0.966), and boards show solvers revisiting a
  shared construction that cannot work.
- **Lossy communication:** about 40 % of note statements were dropped as malformed even after the lossless parser fix;
  peer rejections were never read.

No further screen is justified by the recorded evidence. The A/B was not run; the stage-2 code (live arms, controls,
concurrency smoke, which passed clean on the fleet) stays on its branches, unmerged.

<a id="study-40"></a>

## 2026-11-26 (40): baseline of today's defaults (descriptive, not a decision)

Pre-registered as a baseline for later screens (plans 17fcc96, frozen before the corpus and any call; no adoption rule).
- Arithmetic, roll12fair on fresh hard-v26 (96 cases, seed offset 26400): **85 solved, 0 wrong, 11 abstentions**;
  7.09M generated tokens, 4,362 s wall, 145.2 Wh (1.71 Wh per solved case).
- Coding, R2 + code_elastic on fresh seeds 43-45 (72 cases, offset 15700): **70 solved, 2 wrong, 0 unanswered**;
  1.58M generated tokens, 1,450 s wall, 43.5 Wh (0.62 Wh per solved case).
Runs: runs/swarm-baseline-hard26-v1-roll12fair, runs/coding-baseline-v1 (arm_accounting.json, cases).

<a id="study-41"></a>

## 2026-11-27 (41): night 26/27 November, morning summary

Owner: "work on the swarms all night". Spark_01-04 only (Spark_05/06 went to a model comparison). Every screen was frozen
and pushed before any call, had one focused sol review with narrow fixes verified fail-before/pass-after, ran with the
fleet lease, a raw-gauge idle check and a fenced drain, and every rejection went to independent review. 0 wrong answers in every
arithmetic run of the night. Request seeds turned out not to be honoured by this server (live probe): "paired" seeds
only label attempts; draws are independent.

Screens (independent review idea round 2026-11-26):
- **Idea #1, extend a length-forced rejected agent by a replacement's budget** ([screen](../results/extend-screen-v1/report.json),
  [confirmation](../results/extend-confirm-v1/report.json)): screen PASS (extension 3 vs fresh 1 of 12 recorded failures), frozen
  confirmation on 12 fresh failures from hard-v27/v28/v29 STOP (1 vs 1, the same puzzle). Pooled 4 vs 2 of 24, p = 0.625.
  **Not adopted**; independent review: dead for this variant.
- **Idea #4, fork 8K stems into two 24K continuations** ([report](../results/fork-screen-v1/report.json)): **STOP**, coverage fork 2 vs
  fresh 4 of 12 contested puzzles; 11 % fewer generated tokens but 32 % more prompt tokens. independent review: inconclusive, STOP upheld.
- **Idea #2, independent whole-task restatement** ([report](../results/restate-screen-v1/report.json)): **STOP** at the 2-worker
  floor (0 vs 0 rescues of 12 recorded abstentions; restatements faithful, 0 truncated). Mechanism untested at full swarm
  scale; **parked for cost** (independent review's 864-run retest not run).
- **Idea #5, suspend siblings while a verdict is pending**: offline bound ([report](../results/screen-suspend-siblings/report.json))
  rejected it for arithmetic (0.67 %) and R2 coding (0.50 %); only judge-only coding survived (22.2 %). The only mechanism
  this server allows is holding the next dispatch (bound 12.3 %). Live A/B on 72 fresh judge-only cases
  ([report](../results/coding-suspend-v1/report.json)): **STOP**, solved 69 vs 70, wrong 2 vs 1, energy per solved case 1.07x
  (tokens -10.9 % but wall +15 %). **Closed**; independent review: dead for hold_dispatch.
- **Idea #3, couple sampling randomness across siblings** ([check](../results/idea3-stratified-check/report.json)): the CPU check
  shows exact marginals and halves duplicate first tokens, but the server's speculative decoding draws its own randomness,
  so a fleet screen needs an SGLang change. **Stopped there.**
- A strict-verifier audit found the shared arithmetic verifier lenient about an illegal trailing move; re-checking all 2,854
  accepted answers of the recent runs flipped **0** ([audit](../results/audit-strict-verifier/report.json)).

Adoptions: none. Reverts: none. Defaults unchanged: arithmetic roll12fair, coding R2 + code_elastic.

Baselines of today's defaults (descriptive fillers, each frozen before its corpus/seeds):
- Arithmetic roll12fair, hard-v26..v30 (5 x 96 cases): **425 / 480 solved, 0 wrong**, 1.69 Wh per solved case
  (per corpus 85, 92, 87, 80, 81). hard-v31 running at 07:40 Warsaw.
- Coding R2 + code_elastic, seeds 43-57 and 61-63 (6 x 72 cases): **417 / 432 solved, 15 wrong (3.5 %)**, 0.61 Wh per
  solved case. Coding is not at 0 wrong; any coding screen should be judged against this rate.

Fleet idle (night, from about 19:55Z): about 42 minutes, almost all of it the 2-6 minute merge / freeze / CI-check phase
before each queue item (12 items), plus 3 minutes after the idea #1 launch crash (a judge-client TypeError, fixed with a
test, no model calls made). One test of the idea #1 driver may have sent up to 8 read-only /metrics GETs to the fleet
before network blocking was added to all test harnesses.

<a id="study-42"></a>

## 2026-11-27 (42): differential-consensus gate for coding (offline replay, live A/B)

Idea borrowed from a read-only study of an external swarm design: before accepting a coding answer that passes the
public tests, run the other passing candidates on extra inputs and accept only if they agree.

- **Offline replay** ([report](../results/diffgate-v1/report.json)) on recorded coding runs, references from other cases of the
  same task: flagged 8 of 19 wrong answers (42.1 %) and 2 of 49 correct ones (4.1 %); an any-reference variant flagged
  73.7 % / 16.3 %. 13.9 % of items had no reference. Generator 545K tokens, sandbox 123 s. Blind spot: all 4 wrong
  render_table answers passed (a bug every candidate shares). An arithmetic two-agree early accept was also replayed
  offline and was not worth a screen (3 of 672 cases change; 0.28 % of judge tokens saved).
- **Live A/B** ([report](../results/diffgate-live-v1/report.json)), frozen before any call, 216 cases per arm (seeds 70-78): control =
  production R2 + code_elastic, gate = the same plus the differential gate. Rule: PASS iff wrong(gate) <= 0.6 x control,
  solved(gate) >= control - 3, GPU Wh per solved case <= 1.5 x control.

| arm | solved | wrong | unanswered | agents | server tokens | Wh per solved | wall |
|---|---|---|---|---|---|---|---|
| control | 211 | 5 | 0 | 422 | 4.48M | 0.528 | 3606 s |
| gate | 213 | 3 | 0 | 594 | 8.98M (generator 1.82M) | 0.985 (1.87x) | 6810 s |

  **STOP on energy** (wrong and solved checks pass; wrong exactly at the bound, 3 <= 3.0). The three remaining gate
  errors are all the shared-bug blind spot: render_table seeds 70 and 77, json_select seed 78 (every passer agreed).
  Paired outcomes: 208 both right, 5 fixed by the gate, 3 broken (exact McNemar p = 0.73).

  **Verdict PROVISIONAL**, because the arms ran under different networks: two Mac network outages interrupted the
  gate arm. Gate run 1 was invalidated by the first outage; gate rerun 1 lost every sandbox grade to ssh timeouts on
  the off-LAN route and was stopped; gate rerun 2 ran off-LAN through a launcher-level ssh route to the nodes' Tailscale
  addresses (0 infrastructure failures). Each rerun was a whole fresh arm under the same frozen plan, with an amendment
  committed first (DIFFGATE_GATE_RERUN_AMENDMENT.json, DIFFGATE_GATE_RERUN2_AMENDMENT.json, SSH_ROUTE_AMENDMENT.json).
  Wall time and energy are therefore not strictly comparable; the report file itself prints an unconditional STOP.
  The energy failure looks driven by work, not the network: average fleet power 111.1 vs 110.9 W and energy per
  generated token 24.8 vs 23.4 uWh were the same, while the gate generated 2.0x the tokens; scaling the control's
  energy per token to the gate's tokens gives 1.98x.

  independent review: execution sound; **formally inconclusive / provisional STOP, operationally reject the unchanged v1** rather than
  spend about 3 fleet hours on a paired LAN rerun (held, not run). Retest only a cheaper redesign (cached spec-only
  inputs per task, shorter generator budgets, or a trigger from an existing cheap disagreement signal), frozen on
  development data and evaluated on fresh paired cases with identical transport.

Adoptions: none. Defaults unchanged.

<a id="study-43"></a>

## 2026-11-28 (43): final baselines and swarm idle

Final descriptive baselines, verified against the complete run case records, accounting and runner summaries; all seven frozen plans were committed before their calls. Hard-v33 uses the valid full rerun after the outage.

| baseline | solved | wrong | unanswered | report |
|---|---|---|---|---|
| hard-v33 | 85/96 | 0 | 11 | [swarm-baseline-hard33-v1](../results/swarm-baseline-hard33-v1/REPORT.md) |
| hard-v34 | 86/96 | 0 | 10 | [swarm-baseline-hard34-v1](../results/swarm-baseline-hard34-v1/REPORT.md) |
| hard-v35 | 86/96 | 0 | 10 | [swarm-baseline-hard35-v1](../results/swarm-baseline-hard35-v1/REPORT.md) |
| hard-v36 | 91/96 | 0 | 5 | [swarm-baseline-hard36-v1](../results/swarm-baseline-hard36-v1/REPORT.md) |
| coding s79 (79-81) | 70/72 | 2 | 0 | [coding-baseline-s79](../results/coding-baseline-s79/REPORT.md) |
| coding s82 (82-84) | 72/72 | 0 | 0 | [coding-baseline-s82](../results/coding-baseline-s82/REPORT.md) |
| coding s85 (85-87) | 68/72 | 4 | 0 | [coding-baseline-s85](../results/coding-baseline-s85/REPORT.md) |

The swarm is idle by owner decision on 2026-11-27. Defaults remain arithmetic **roll12fair** and coding **R2 + code_elastic**. No adoption or revert follows from these baselines.

The diff gate remains a **provisional STOP**: wrong and solved checks pass, energy fails, and the network conditions differed between arms. The paired LAN rerun remains held in `.runtime/queue/hold/98-diffgate-paired-lan.sh`; it has not been run. Serving endpoints were left as is; this wrap-up used local evidence only.

## Incidents

- Coding source a41c312 still had a 1800 s per-request wall limit; Inkling at ~18 tok/s per request under 25-request load
  needs ~30 min for 32K tokens. Six agents hit it; the runner stopped admissions as designed; fixed in c2eb89e (14400 s),
  plan amendment 1, faulted and unstarted agents rerun (v1b).
- One tuning measurement (ragged verify at 24 requests) was invalidated by my own restart; reported as invalid.

## Reports

[inkling-hard4-v1](../results/inkling-hard4-v1/REPORT.md) · [inkling-coding-hard-v1](../results/inkling-coding-hard-v1/REPORT.md) ·
[inkling-bugbench-long-v1](../results/inkling-bugbench-long-v1/REPORT.md) · [disproof-selection-v1](../results/disproof-selection-v1/REPORT.md) ·
[efficiency-v1](../results/efficiency-v1/REPORT.md) · [inkling-hard5-v1](../results/inkling-hard5-v1/REPORT.md) ·
[swarm-cancel-hard6-v1](../results/swarm-cancel-hard6-v1/REPORT.md) · [swarm-escalate-hard7-v1](../results/swarm-escalate-hard7-v1/REPORT.md) · [coding-earlystop-v1](../results/coding-earlystop-v1/REPORT.md) · [swarm-burst-hard8-v1](../results/swarm-burst-hard8-v1/REPORT.md) · [coding-stagger-v1](../results/coding-stagger-v1/REPORT.md) · [swarm-repair-hard9-v1](../results/swarm-repair-hard9-v1/REPORT.md) · [swarm-strategy-hard10-v1](../results/swarm-strategy-hard10-v1/REPORT.md) · [swarm-width3-hard11-v1](../results/swarm-width3-hard11-v1/REPORT.md) · [swarm-cap12-hard12-v1](../results/swarm-cap12-hard12-v1/REPORT.md) · [mixed-task-v1](../results/mixed-task-v1/REPORT.md) · [swarm-cap12-hard14-v1](../results/swarm-cap12-hard14-v1/REPORT.md) · [swarm-fair-hard22-v1](../results/swarm-fair-hard22-v1/REPORT.md) · [coding-reserve-v1](../results/coding-reserve-v1/REPORT.md) · [coding-reserve-v2](../results/coding-reserve-v2/REPORT.md) · [swarm-fair-hard23-v1](../results/swarm-fair-hard23-v1/REPORT.md) · [coding-elastic-v1](../results/coding-elastic-v1/REPORT.md) · [coding-elastic-v2](../results/coding-elastic-v2/REPORT.md) · [collab-s0-v1](../results/collab-s0-v1/REPORT.md) · [collab-s0-v2](../results/collab-s0-v2/REPORT.md) · [collab-s0-v3](../results/collab-s0-v3/REPORT.md) · [collab-s1-v1](../results/collab-s1-v1/REPORT.md) · [collab-s1-v2](../results/collab-s1-v2/REPORT.md) · [extend-screen-v1](../results/extend-screen-v1/report.json) · [extend-confirm-v1](../results/extend-confirm-v1/report.json) · [fork-screen-v1](../results/fork-screen-v1/report.json) · [restate-screen-v1](../results/restate-screen-v1/report.json) · [coding-suspend-v1](../results/coding-suspend-v1/report.json) · [diffgate-v1](../results/diffgate-v1/report.json) · [diffgate-live-v1](../results/diffgate-live-v1/report.json)

---

This section retains the original study descriptions and their limitations. Statements about active follow-ups or serving state describe that historical snapshot; the current status is idle.

## Original study and earlier follow-ups

**Historical snapshot from the original landing page.** [Article draft](../ARTICLE_DRAFT.md) · [X draft for the owner to publish](../X_POST_DRAFT.md) · [DeepSeek reference](../results/reference-deepseek-v1-analysis/REPORT.md) · [Reproduction guide](../REPRODUCING.md). [Published raw evidence: 85.9 MB archive, manifests and checksums](../EVIDENCE_RELEASE.md).

**Historical follow-up research:** [frozen 168-case emission/format experiment](../FOLLOWUP72.md), informed by a high-effort independent design review and independent diagnostics. No new Nemotron quality score is available yet; gains on the already-seen 24 tasks will be exploratory and separate from the frozen overnight release.

The frozen primary comparison covers 900 attempts:
24 arithmetic tasks and 18 Python-function tasks, three sampling seeds, and
strong solo, independent-ensemble, shared-state and voting controls. Repeated
seeds remain clustered by task. See [EVALUATION_SELECTION.json](../EVALUATION_SELECTION.json)
for the primary protocol and [EVALUATION_PROGRESS.md](../EVALUATION_PROGRESS.md)
for completed coverage and instrumentation exclusions. Development results below
do not establish a generally superior agent architecture.

A standard-library Python prototype for four independent Nemotron replicas.
Arithmetic moves are verified with `fractions.Fraction`. Generated Python
functions are evaluated separately in constrained, CPU-only Docker containers;
feedback tests guide repairs, and a frozen selected candidate receives one
held-out evaluation. See [EXPERIMENT_PLAN.md](../EXPERIMENT_PLAN.md) for the design.

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

## Original study evidence

The separate native DeepSeek TP4 reference completed **72/72 arithmetic and 54/54 coding attempts**, on the same 24/18 tasks and three repetitions, with independent verification. This is a pinned custom abliterated checkpoint and a different serving/compute recipe, not an equal-cost model ranking. Native client usage is complete; global server token cost is unknown. [Reference comparison and limitations](../results/reference-deepseek-v1-analysis/REPORT.md) · [independent audit](../results/reference-deepseek-v1-audit/AUDIT.json). The planned additional model reference was unavailable because the account hit its weekly usage limit; the optional GLM hybrid was not run.

**Nemotron study runtime: vLLM 0.32.0 ARM64, DSpark3, four independent replicas.** At the overnight study closure these replicas were stopped and retained, and native DeepSeek TP4 was restored. The new follow-up runs in a separate coordinated window; see [current follow-up status](../FOLLOWUP72.md). The uniform runtime-v2 study completed **900 primary attempts**, **80 supplemental solo-control attempts** (8 development and 72 evaluation), and **45 corrected loaded-queue cohorts / 2,016 attempts** (36 development batches and 9 evaluation batches). [Progress and exclusions](../EVALUATION_PROGRESS.md).

The arithmetic primary four-sample reasoning ensemble solved **49/72 attempts (68.1%)**; sequential own-feedback refinement solved **45/72 (62.5%; task-cluster 95% interval 47.2–77.8%)**, versus **18/72 (25.0%)** for one reasoning call. The paired ensemble-minus-refinement difference is **+5.56 percentage points (95% interval −5.56 to +16.67)**, spanning zero. These are repeated attempts on **24 distinct tasks**, with separate execution schedules and different realized costs. [Completed stronger-solo comparison](../results/solo-control-v2/complete-comparison/solo-comparison/REPORT.md).

Under load, shared frontier 8 recorded **12/96 successes at 21.31 successful attempts/minute**; four full plans recorded **48/96 at 2.87/minute**. These describe quality/rate tradeoffs for finite batches, not a universal efficiency winner. Admission was selected on development within **1/2/4/8 cases per node**; that bounded sweep does not establish globally optimal solo saturation. Four cheap-policy arms were a later exploratory amendment. [Completed throughput report, costs and figures](../results/throughput-timeoutguard-20261115/REPORT.md).

Independent outer-parent coding confirmation completed **824 unique grading jobs for all 324 cases / 323 selected artifacts**. Original holdout outcomes agree in every case: **295 passes, 28 failures and one no-candidate failure**. Original scores are preserved; public examples and posthoc probes remain separate. This confirms finite test outcomes without repairing the original grader or proving general correctness. [Confirmation analysis](../results/coding-confirmation-v1-analysis/NOTES.md) · [grader audit and limitations](../CORRECTNESS_AUDIT.md).

The runtime-v2 serving qualification completed **416 mixed requests including warmups**, with **69,158 output tokens / 39.008007 full wall seconds = 1,772.918 output tok/s** and zero recorded transport errors. Separate short-JSON probes passed **100/100 at T0 and 100/100 at T0.8**. These bounded serving checks do not measure task-solving efficiency. The historical v0.27.1 DSpark comparison measured **+51.40%** on its particular matched workload; that is not a measured gain for the current runtime. [Serving reports and exact pins](../SERVING.md).

The original [direct-assignment graph-search study](../SEARCH_SELECTION.json) is complete: **0/252 core evaluation cases and 0/288 extended 64-call cases solved**. Across development and evaluation, 568 cases used 22,912 model calls, including reviewer reuse and ordinary/quality-weighted voting. Independent replay checked every one of 22,422 assignment proofs; malformed cardinality/domain responses were genuine candidate failures. The separately budgeted CPU controls solved 30/36 evaluation cases with min-conflicts and 18/36 with genetic search. [Independent audit](../results/csp-independent-audit-20261116/FINAL_AUDIT.json).

In the separate [reusable-program experiment](../PROGRAM_SEARCH_SELECTION.json), Nemotron wrote Python solvers scored only on four development graphs. Four independent chains selected programs solving **47/48 original evaluation outcomes**, compared with **29/48** for sequential refinement, at 16 training calls per program. These are **four paired trained programs per method on 12 reused graphs**, with wide uncertainty; generating a program and executing it on CPU is a different workflow from emitting assignments. [Completed report and figures](../results/program-search-v1-analysis/REPORT.md) · [independent protocol audit](../results/program-search-v1-audit/NOTES.md). Prospectively planned confirmation on **96 new graphs** is now complete: **376/384 (97.92%)** for independent chains and **237/384 (61.72%)** for sequential refinement. Three independent-chain programs each solve **96/96**; all eight sources were frozen before these 768 CPU-only grades, with zero extra model calls or repairs. [Fresh confirmation report, cost scope and figures](../results/program-confirmation-v1-analysis/REPORT.md) · [independent audit](../results/program-confirmation-v1-audit/AUDIT.json). The late exploratory reasoning-enabled assignment cohort also completed **0/96**: all **1,464 assignment calls** exhausted the 4,096-token cap in separate reasoning and returned no answer content; 72 review calls completed normally. This is an observed output-budget/format failure for this configuration, not evidence of general inability to color graphs. [Exact completed audit](../results/csp-thinking-on16-late-audit-20261116/FINAL_AUDIT.json). Earlier assignment results remain unchanged.

The separate program-context reviewer experiment completed **47/48 original outcomes and 376/384 known-96 outcomes**, matching the independent-chain totals in these runs. Four training episodes each spent 16 calls: ten program proposals and six reviews. These late exploratory runs do not isolate a causal reviewer effect. [Completed report, costs and real review lineage](../results/program-review-v1.1-analysis/REPORT.md) · [producer audit](../results/program-review-v1.1-audit/FINAL_AUDIT.json) · [384-grade audit](../results/program-review-confirmation-v1.1-audit/AUDIT.json). The pre-call phase-stop defect was fixed and [audited](../results/program-review-precall-audit-20261116/PRECALL_AUDIT.json) before any variant calls.

The optional adversarial JSON-schema qualification passed 24 entries, then failed at 64 entries when a 512-token response ended in whitespace before completing JSON. It stopped after two calls; the third probe and 84-case quality study were not run. This is not a general backend-incompatibility result. [Exact qualification records](../results/guided-schema-qualification-20261116/README.md) · [independent audit](../results/guided-schema-qualification-v1-audit/AUDIT.json).

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

The [first 100-agent democracy pilot](../results/traces/democracy-100-952.jsonl)
on target 952 completed **1,000 calls**, **16,595 completion tokens** in
**29.700536 seconds**, with **0 infrastructure failures** and **0 successes**.
This is one thinking-off run; it establishes neither method superiority nor a
thinking-on/off comparison. Comparative quality and the value of reputation
remain unestablished. See [PILOT.md](../PILOT.md) for the independent run, a solved easy case, output-budget failures and included traces.

The separate [governance pilot](../GOVERNANCE.md) includes an interleaved 18-run
follow-up with stable candidate identifiers: independent paths solved 2/6 games,
ordinary democracy 0/6, and democracy with verified-solution acceptance 1/6.
The 500-call ceiling censored every ordinary-democracy trajectory; these small,
stochastic experiments do not rank methods generally. Full prompts, costs and
negative earlier cohorts are retained. [PILOT.md](../PILOT.md) also records reasoning
budget and reputation-pipeline checks.
