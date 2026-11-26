# Night 2026-11-20/21: Inkling-2-Mini replaces Nemotron in the Swarm Lab

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

- [Fresh replication](inkling-hard5-v1/REPORT.md) on arithmetic-hard-v5 (plans frozen before the corpus existed): swarm 78 vs DeepSeek 76 (+8/-6).
  Pre-registered pooled test over 192 cases: 168 vs 161, +14/-7 (p = 0.19), 0 wrong; One Inkling 130 is clearly below DeepSeek (p = 3e-6).
  So the swarm matches DeepSeek, it does not beat it significantly.
- Arithmetic hard-v4 swarm vs DeepSeek paired +6/-1 (p = 0.125); vs Nemotron swarm +9/-1 (p = 0.02). Judge: 0 false accepts in 330.
- Coding swarm vs DeepSeek +10/-2 (p = 0.039); One Inkling vs DeepSeek +8/-6 (p = 0.79).
- [Executable disproofs](disproof-selection-v1/REPORT.md) (astra idea #1): contracts written from the public task alone
  are the best arbiter-free code selector so far: Nemotron candidates 56 -> 59 (judge 57, output vote 55; oracle 64),
  Inkling candidates 69 -> 70 (oracle 71).

## Does it pay now? ([efficiency-v1](efficiency-v1/REPORT.md), Fable idea #6)

Same four Sparks, GPU-rail energy from 1 Hz `nvidia-smi`: the Inkling fleet (four replicas) produces 1,412 tok/s at
0.083 J/token; DeepSeek TP4 at its 16 slots 276 tok/s at 0.44 J/token. Per solved task, One Inkling solves ~5x more coding
tasks per hour than One DeepSeek at ~1/5 of the GPU energy (equal accuracy), and is cheaper on bugs and arithmetic too.
The Inkling swarm is the most accurate system and costs more energy per solved task than One DeepSeek.

## Day 2026-11-21: cancel the other agents once one plan is accepted ([swarm-cancel-hard6-v1](swarm-cancel-hard6-v1/REPORT.md))

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
[One DeepSeek on the same hard-v6 tasks](swarm-cancel-hard6-v1/DEEPSEEK.md): 85/96 (swarm A 86, paired +3/-2) at 1.29 Wh per
solved case, the same as swarm B (1.30). Exploratory pooled v4+v5+v6 (288): swarm 254 vs DeepSeek 246 (+17/-9, p = 0.17).

## Day 2026-11-21 (2): escalation, B+ ([swarm-escalate-hard7-v1](swarm-escalate-hard7-v1/REPORT.md))

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
[One DeepSeek on the same hard-v7 tasks](swarm-escalate-hard7-v1/DEEPSEEK.md): 79/96. **B+ vs One DeepSeek 90 vs 79, paired
+13/-2 (p = 0.007)**, 0 wrong, at 1.48 vs 1.66 Wh per solved case on the same four Sparks: the first significant win of
the swarm over DeepSeek. Hybrid (DeepSeek only on B+'s 6 abstentions): 92/96.

## Day 2026-11-21 (3): coding swarm early stop, live ([coding-earlystop-v1](coding-earlystop-v1/REPORT.md))

Frozen plans (669665e) before any call with fresh seeds 4-6 on coding-hard-v1 (72 cases, 8 agents of 32K).

| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy per solved case |
|---|---:|---:|---:|---:|
| F: all 8 agents to the end, slot-order first passing | 66 | 99.8K | 96 min | 2.74 Wh |
| **E: first proposal passing the public tests ends the case** | **69** | **62.8K (-37 %)** | **61 min (-36 %)** | **1.69 Wh** |

On the same proposals (inside F), the first passing proposal in time is the better pick than the first in slot order
(71 vs 66). **Early stop is now the default for the coding swarm.** Serving changed before this study (owner): Inkling
runs with `--mem-fraction-static 0.75` (KV ~1.08M tokens per node; MemAvailable >= 24.3 GiB under full load).

## Night 2026-11-21 (4): escalate earlier and further? ([swarm-burst-hard8-v1](swarm-burst-hard8-v1/REPORT.md))

Fresh hard-v8 (plan 4eb69e7 frozen first). B+ (default) 91/96 at 47.3K tokens/case, 66 min, 1.36 Wh per solved case;
B++ (cap 12 + 900 s burst to 8 in flight) 90/96 at 70.7K, 91 min, 1.94 Wh. Agents 9-12 rescued 4 cases, but the time
trigger fired 21 times (9 needlessly) and the burst agents slowed every other case. **B+ stays the default.**

## Night 2026-11-22 (5): coding swarm, start 4 agents and add 4 only if needed ([coding-stagger-v1](coding-stagger-v1/REPORT.md))

Fresh seeds 7-9 on coding-hard-v1 (plans ec69a43 frozen first), both arms with early stop. All 8 agents at once: 69/72,
59.8K tokens/case, 60 min, 1.66 Wh per solved case. Staggered (4 first, 4 more after 300 s or when the first four fail):
**69/72, 50.0K tokens/case (-16 %), 52 min (-13 %), 1.42 Wh**; the second wave was needed in 39 of 72 cases.
**Coding default is now early stop + staggered start.**

## Night 2026-11-22 (6): escalation agents that see the judge's critique ([swarm-repair-hard9-v1](swarm-repair-hard9-v1/REPORT.md))

Fresh hard-v9 (plan 8b28aed frozen first; a harder corpus). B+ 86/96 (0 wrong, 69.1K tokens/case); escalation agents
given every rejected plan with the judge's reason: 83/96, and their success rate halved (4/73 vs 9/82 accepted;
4 vs 8 strict rescues). Feedback anchors the agents. **B+ (fresh escalation agents) stays the default.**
[One DeepSeek on hard-v9](swarm-repair-hard9-v1/DEEPSEEK.md): 77/96; B+ 86 (+12/-3, p = 0.035). **Pre-registered pooled
hard-v7 + v9: B+ 176 vs One DeepSeek 156 of 192, paired +25/-5 (p = 0.0003), 0 wrong**: the swarm's lead over DeepSeek
replicates on fresh tasks. Hybrid (DeepSeek only on B+ abstentions): 181/192.

## Cost of the policies measured 2026-11-21/22 ([energy-defaults-20261122](energy-defaults-20261122/tables.md))

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

## Morning 2026-11-22 (7): escalation agents with distinct strategy hints ([swarm-strategy-hard10-v1](swarm-strategy-hard10-v1/REPORT.md))

Fresh hard-v10 (plan 37b82fc frozen first). B+ 83/96 (58.3K tokens/case, 1.76 Wh per solved case); escalation agents
with one of four task-agnostic strategy hints each: **86/96, 0 wrong, 55.4K tokens/case, 1.60 Wh**, escalation success
5/60 vs 2/65 accepted, 4 vs 1 strict rescues (small counts; paired +5/-2). Frozen rule met: **roll8strategy is the new
arithmetic default** (B+ plus diverse escalation). Diversity helps where critique (hard9) hurt.

## Day 2026-11-22 (8): three agents in flight instead of four ([swarm-width3-hard11-v1](swarm-width3-hard11-v1/REPORT.md))

Fresh hard-v11 (plan a320690 frozen first). Default roll8strategy (4 in flight) 83/96, 61.2K tokens/case, 79 min; 3 in
flight 81/96 with **+17 % tokens**, +44 % wall, +37 % energy: fewer racers mean a later first accept (cancelled agents ran
longer) and more escalations. **4 in flight stays.** (Caveat: the 3-wide arm also used only ~15 agents per node.)

Prefix cache (from the server counters of every arm today): the SGLang radix cache already serves 94-97 % of the
arithmetic prompt tokens and 65-74 % of the coding prompt tokens; the prefill that is still computed is 2-3 % of the
generated tokens. Routing a case's agents to one node could save at most the 3 extra computations of one ~500-token
prompt per case, well under 1 % of the work, so no fleet study was spent on it.

## Day 2026-11-22 (9): escalation cap 12 instead of 8 ([swarm-cap12-hard12-v1](swarm-cap12-hard12-v1/REPORT.md))

Fresh hard-v12 (plan 0a475c3 frozen first). Default roll8strategy 81/96 (62.0K tokens/case, 79 min); cap 12 85/96, 0 wrong,
2 cases answered only by agents 9-12, paired +6/-2 (p = 0.29), 2.28 vs 1.85 Wh per solved case; +24 % tokens and +29 % wall
(my frozen limits were 20 % / 25 %). **Cap 12 = max-accuracy mode**; cap 8 stays the efficiency default until a
replication on a fresh corpus (queued next) shows whether the gain holds.

## Day 2026-11-22 (10): arithmetic and coding swarms at the same time ([mixed-task-v1](mixed-task-v1/REPORT.md))

Both defaults on fresh work (arithmetic-hard-v13, coding seeds 10-12), plans a717252 frozen first. Together (10 + 10
requests per node): 141 min, 267 Wh, arithmetic 86/96 (0 wrong), coding 67/72. One after the other (20 per node each):
124 min, 238 Wh, 88/96 and 65/72. **Run them one after the other**: the static split leaves half the fleet idle once the
shorter workload ends; accuracy is the same within noise.

## Night 2026-11-22/23 (11): cap 12 replicated ([swarm-cap12-hard14-v1](swarm-cap12-hard14-v1/REPORT.md))

Fresh hard-v14 (plan 0de332a frozen first). Cap 12 88/96 vs cap 8 86/96, 0 wrong, 2 cases answered only by agents 9-12;
pre-registered pooled hard-v12 + v14: 173 vs 167 of 192 (+9/-3, p = 0.15), 4 noise-free late rescues, 0 wrong. Cost:
+17 % tokens and +25 % wall on hard-v14 (1.96 vs 1.65 Wh per solved case), paid only on cases 8 agents cannot solve.
**roll12strategy (cap 12) is now the arithmetic default** (owner: quality first).

## 2026-11-23 (12): coding failure-driven replacement ([coding-roll-v1](coding-roll-v1/REPORT.md))

Fable idea 1, plans 205783b frozen before seeds 13-15. Early stop in every arm. S (stagger 4+4 at 300 s, old default)
65/72, 5 wrong (public tests pass, hidden fail); R4 (replace failures, 4 in flight) 69, 2 wrong, -25 % tokens; R2 (2 in
flight) 71, 1 wrong, -52 % tokens, 1.01 vs 1.52 Wh per solved, R2 vs S +6/-0 (p = 0.031); a pool replay puts R2 at
about 69 solved, so part of the +6 is seed luck. **R2 is the coding default** (not worse, half the tokens).

## 2026-11-23 (13): loop watchdog ([swarm-loop-hard15-v1](swarm-loop-hard15-v1/REPORT.md))

Fable idea 3, plans 9ffceec before hard-v15 (6919fe4). D (roll12strategy) 85/96 vs L (+ zlib loop watchdog) 83/96, 0 wrong
in both; 102 streams stopped, 0 of their forced answers accepted. Frozen rule: adopt (L/D tokens 0.918, partly a D-side
infra waste). Replay: 9 of 708 streams that met the criterion still gave their case's correct answer, 8 of them via a
forced answer at the thinking-budget limit (astra review: not proven loop escapes; a 54-check trigger would spare all 9).
**Watchdog provisionally not adopted** (quality first); fair follow-up: none vs forced answer vs a "change approach" nudge.

## 2026-11-23 (14): table relay prototype screen (codex-tablerelay, not a study)

24 development six-number cases: 0 solved, 0 wrong; builder tables covered 0.07 % of reachable values and 92 % of kept
rows were false. Astra review: the screen was unfair to the idea (all 360 builders hit the 1,600-token thinking cap and
answered only after forced closure; ~147 rows per group). **This prototype is rejected; the idea stays open** for a fair
re-screen (worked examples, one group per builder, calibrated budgets, direct answer vs thinking).

## 2026-11-23/24 (15): escalation hints on a shared first wave ([swarm-hints-hard16-v1](swarm-hints-hard16-v1/REPORT.md))

Fable ideas 4 + 5. One default first wave on 192 six-number cases of fresh hard-v16 (144 solved, 0 wrong), then four
escalation-only arms on the 48 strict-hard cases, same seeds, only the hint text differs. Rescued: no hints 19, current
hints 14, hints 0+2 16, **last-move partition hints 31** (+18/-1 vs current, p = 7.6e-5), 0 wrong in every arm, P with
23 % fewer tokens per case. The current hints show no benefit. **Owner rule (2026-11-24): generic swarm only, so P is not
adopted and its confirmation was cancelled** (all hints here are arithmetic-specific).

## 2026-11-24 (16): round 3 on hard-v17 ([swarm-round3-hard17-v1](swarm-round3-hard17-v1/REPORT.md))

Worker with one retry on upstream transport loss and judge retry in every arm. D (default) 87/96, L (prompt sentence
"unused numbers are allowed; stop as soon as the target appears") 88/96, 0 wrong both; L passed its frozen rule but is a
task-specific prompt change: **not adopted (owner rule)**. Add-on X, slots 12-19 on D's 9 abstentions: 2 rescued, 0 wrong,
+28 % of D's tokens: **more agents is a generic mechanism; cap 20 passes, live load-gated version next**. Recall pass:
dev screen 0/30 (262 plans, none correct), task-specific anyway. Closers: task-specific as implemented (arithmetic wanted
list), not run on hard-v17.

## Proposal: a generic default without hints

The owner rule also covers the escalation strategy hints in today's default `roll12strategy`. Existing data says they
buy nothing: hard-v10 (cap 8) hints vs none +5/-2 (p = 0.45); hard-v16 strict-hard cases no hints 19 vs strategy hints 14
rescues (+10/-5 for no hints, p = 0.30) at equal tokens; Fable's pooled replay unhinted 19/53 vs hinted 11/55 rescues.
Proposed default: `roll12cancel` (cap 12, failure-driven replacement, cancel on accept, no hints). Confirmation planned on
a fresh corpus together with the live idle-capacity escalation: roll12strategy vs roll12cancel vs roll12idle.

## 2026-11-24 (17): generic default and idle-capacity escalation ([swarm-generic-hard18-v1](swarm-generic-hard18-v1/REPORT.md))

Owner rule: generic swarm only. Fresh hard-v18, plan 98a267a frozen first, each arm alone, 0 wrong in every arm.
S roll12strategy (old default, task-specific hints) 83/96; **G roll12cancel (same policy, no hints) 85/96** (+4/-2), fewer
tokens and Wh per solved: **G is the new arithmetic default** (frozen rule passed). GI roll12idle (G plus up to 8 extra
unhinted agents per failed case while a node holds < 12 requests) 86/96, 1 case answered by slots 12-19, but arm wall
1.24 x G (gate 1.10) and +25 % tokens: not adopted.

## 2026-11-24 (18): coding R2 replicated ([coding-roll2-v1](coding-roll2-v1/REPORT.md))

Fresh seeds 16-18: R2 71 vs S 68 of 72 (+4/-1), wrong 1 vs 3, -48 % tokens. Pooled over both studies R2 142 vs S 133 of
144, wrong 2 vs 8. **R2 stays the coding default.** Next running: coding-roll3-v1, R2 vs R1 (one agent in flight).

## 2026-11-24 (19): coding R1 ([coding-roll3-v1](coding-roll3-v1/REPORT.md))

Seeds 19-21: R1 (one agent in flight) 66 vs R2 67 of 72, wrong 6 vs 4, -33 % tokens, +30 % wall: **R2 stays**.

## 2026-11-24 (20): generic artifact relay, dev screen ([relay-screen-hard18-v1](relay-screen-hard18-v1/REPORT.md))

Astra's fair generic closer test. On 14 deduplicated generic abstentions of hard-v18 (7 puzzles), up to 4 uniformly sampled
failed-agent artifacts (last 12,000 characters) went to new workers with one fixed sentence ("Another solver worked on this
exact task ... use whatever is correct in it, finish the task"), against the same number of fresh equal-budget workers:
**RELAY 4 vs REPLACE 0 rescues**, 0 wrong in both, generation tokens -8 % but total compute +17 % (the artifacts are prompt
input). Gate passed; a replication on 29 unhinted esc_none abstentions of hard-v16 is running, then an in-swarm study
(roll12relay: escalation agents receive one failed artifact) on a fresh corpus.

## 2026-11-24 (21): artifact relay replicated ([relay-screen-hard16-v1](relay-screen-hard16-v1/REPORT.md))

29 unhinted esc_none abstentions of hard-v16 (6 puzzles), plan 80c6f4f frozen first: **RELAY 5 vs REPLACE 2 rescues**
(relay-only 4, replace-only 1), 0 wrong; total compute +21 % (artifacts are prompt input). Pooled over both screens
RELAY 9 vs REPLACE 2 of 43, 0 wrong: the pre-registered gate for the in-swarm study passed; swarm-relay-hard19-v1
(roll12cancel vs roll12relay, plan 7ee58f6, corpus 61ca1bf) started 18:40Z.

## 2026-11-24/25 night (22-25): generic mechanisms

- **Relay in the swarm** ([swarm-relay-hard19-v1](swarm-relay-hard19-v1/REPORT.md)): roll12cancel 84 vs roll12relay 83 of 96, 0 wrong,
  +12 % total compute: **not adopted** (the screen rescues did not turn into extra solves inside the swarm); to astra review.
- **Work-conserving widening** ([swarm-wide-hard20-v1](swarm-wide-hard20-v1/REPORT.md)): roll12cancel 87 vs roll12wide 87, 0 wrong,
  wall 0.90x, GPU Wh 0.91x, tokens +1 %: **roll12wide is the new arithmetic default** (generic; same answers, less wall and energy).
- **Dense relay window** ([relay-window-v1](relay-window-v1/REPORT.md)): dense 1 vs tail 1 of 38: tail stays (moot without relay).
- **Judge replays** ([judge-replay-v1](judge-replay-v1/REPORT.md)): a generic coding judge as a second key would reject 20/31 wrong
  winners but also 61/684 correct (8.9 % > 5 % cap): not pursued; a second arithmetic judge on forced answers found 0 false
  accepts in 2,787 invalid forced plans and rejected 0 of 54 valid ones: nothing to gain. Rejections to astra review.

## 2026-11-25 (26): One DeepSeek on the coding-roll3 cases ([deepseek-coding3-v1](deepseek-coding3-v1/REPORT.md))

Owner OK; plan 11fd27d frozen before any call. Native DeepSeek V4.1 TP4, one thinking call per case, same 72 cases:
DeepSeek 57/72 (0 wrong, 15 unanswered) vs swarm R2 67/72 (4 wrong) and R1 66/72 (6 wrong). Paired: swarm R2 +11/-1
(p = 0.006), R1 +13/-4 (p = 0.049). Hybrid R2 + DeepSeek on R2's 1 unanswered case: 67/72. Wh per solved: DeepSeek 2.64,
R2 1.33, R1 1.32. DeepSeek never answered wrong but left 21 % unanswered; the swarm answers almost everything at half the
energy per solved case, with 4-6 wrong answers that pass the public tests.

## 2026-11-25 (27): generic Atom-of-Thoughts decomposition ([swarm-aot-hard21-v1](swarm-aot-hard21-v1/REPORT.md))

Owner-approved (Teng et al. 2025, arXiv 2502.12018; taskgraph idea credited to alkimiadev). Fresh hard-v21, plans 58257fb,
v2.9.2 recipe serving, roll12wide in both arms, same 32,768-token budget per agent. Plain 89/96 vs AoT 82/96, 0 wrong
in both; plain-only 7, AoT-only 0 (p = 0.016); AoT 2.1x server tokens, 2.15x wall, 3.46 vs 1.50 Wh per solved. Nearly
every AoT agent decomposed and contracted (326/333); the split budget leaves the final solve only 16K of thinking,
which these hard search tasks need in one stream. **AoT not adopted** (rejection to astra review); coding AoT running.

## 2026-11-25 (28): AoT on coding ([coding-aot-v1](coding-aot-v1/REPORT.md))

code_aot 66/72 vs plain code_xl 68/72 (AoT-only 3, plain-only 5, p = 0.73), 3 vs 4 wrong, 3 unanswered, 2.5x tokens,
1.78 vs 0.64 Wh per solved: **not adopted** (with arithmetic AoT, both rejections go to astra).

## 2026-11-25 (29): coding without provided tests ([coding-notests-v1](coding-notests-v1/REPORT.md))

Owner question: what does the swarm lose without given tests? Same 72 fresh cases, scored on all hidden tests. Public
tests (default) 69/72, 3 wrong; no tests + Inkling judge acceptance (16,384-token judge) 70/72, 2 wrong; no tests + the
agents' own tests 68/72, 1 wrong, 3 unanswered. **No measurable accuracy loss** (paired +3/-2 and +3/-4, p = 1), but about
2x wall and 2.2x energy per solved case (0.77 -> 1.65-1.72 Wh). Even at 16,384 thinking tokens 51 % of judge verdicts
were forced after the cap.

## 2026-11-26 (30): water-filling admission ([swarm-fair-hard22-v1](swarm-fair-hard22-v1/REPORT.md))

roll12fair (every case open from the start; a free agent slot goes to the case with the fewest agents in flight, at
most 4 before a case's first failure and 8 after, cap 12) vs roll12wide on 96 fresh hard-v22 cases: 82 vs 80 solved,
0 wrong in both, F-only 5 / W-only 3 (p = 0.73); arm wall 0.91x, server tokens 0.90x, energy 0.91x (2.06 vs 2.32 Wh
per solved). Frozen rule met: **roll12fair replaces roll12wide**. Cost: the time to an answer per case rises (median
475 s vs 218 s from case start), because cases share the slots instead of being served one batch at a time; the gain
is batch throughput, not single-case latency. Idea: IDEAS-swarm-round5-fable.md idea 2.

## 2026-11-26 (31): elastic answer reserve in coding ([coding-reserve-v1](coding-reserve-v1/REPORT.md))

Replay screen of 116 recorded cut-off coding agents (19 N rows rerun after the multi-token end-of-thinking fix,
merged under the same frozen gate): E 89 / N 85 feedback passes, both qualify, N preferred (>= 90 % of E) ->
code_reserve (an answer cut by length continues in the same sequence in 2,048-token steps, at most 10,240 answer
tokens; thinking cap 26,624 of the 32,768 budget). Study on seeds 28-30 (72 cases): R2 + reserve 71/72, 1 wrong vs R2
70/72, 2 wrong (reserve-only 1, plain-only 0, p = 1); 0 cut-off answers vs 5; tokens 0.82x, wall 0.67x, 0.52 vs 0.74 Wh
per solved. Frozen rule met: code_reserve was adopted, **then reverted** after the failed replication below. Idea: IDEAS-swarm-round5-fable.md idea 1.

## 2026-11-26 (32): reserve replication FAILED, adoption reverted ([coding-reserve-v2](coding-reserve-v2/REPORT.md))

Same plans and rule on fresh seeds 31-33: R2 + reserve 66/72, **6 wrong** vs R2 71/72, 1 wrong (plain-only 5, reserve-only 0,
p = 0.06). Pooled v1+v2: 137 / 7 wrong vs 141 / 3. I adopted code_reserve on a +1 case that the replication reversed;
**the coding default is plain R2 again**. Investigation: the arms also differ in the first-call thinking cap (26,624 vs
30,720), but five of the six wrong answers closed their own thinking below either cap. Same-seed agents diverge within
about 60 characters on this serving, so the arms are independent samples; the same slot won in all five flipped cases,
and paired thinking length is unchanged (p = 0.19). No mechanism found beyond sampling variance, plus one answer forced
at the lower cap (astra: pairing by task stays valid; selection effects are not excluded; RETEST code_elastic, which keeps
the 30,720 cap, is queued as coding-elastic-v1 on seeds 37-39). Lesson: a single-study adoption that wins on efficiency at +1 quality needs its replication before it
becomes the default.

## 2026-11-26 (33): water-filling replicated ([swarm-fair-hard23-v1](swarm-fair-hard23-v1/REPORT.md))

Same plan and rule on fresh hard-v23: roll12fair 88 vs roll12wide 86, 0 wrong in both (F-only 4, W-only 2, p = 0.69);
wall 0.93x, tokens 0.90x, energy 0.93x. Pooled with hard-v22: 170 vs 166 of 192, 0 wrong. **roll12fair stays the
arithmetic default for batch runs.** The per-case latency cost (median time to an answer 567 s vs 300 s) appears only in
batches; single-task use is unaffected by construction (same 4 / 8 / 12 limits, nothing to share), not measured.

## Incidents

- Coding source a41c312 still had a 1800 s per-request wall limit; Inkling at ~18 tok/s per request under 25-request load
  needs ~30 min for 32K tokens. Six agents hit it; the runner stopped admissions as designed; fixed in c2eb89e (14400 s),
  plan amendment 1, faulted and unstarted agents rerun (v1b).
- One tuning measurement (ragged verify at 24 requests) was invalidated by my own restart; reported as invalid.

## Reports

[inkling-hard4-v1](inkling-hard4-v1/REPORT.md) · [inkling-coding-hard-v1](inkling-coding-hard-v1/REPORT.md) ·
[inkling-bugbench-long-v1](inkling-bugbench-long-v1/REPORT.md) · [disproof-selection-v1](disproof-selection-v1/REPORT.md) ·
[efficiency-v1](efficiency-v1/REPORT.md) · [inkling-hard5-v1](inkling-hard5-v1/REPORT.md) ·
[swarm-cancel-hard6-v1](swarm-cancel-hard6-v1/REPORT.md) · [swarm-escalate-hard7-v1](swarm-escalate-hard7-v1/REPORT.md) · [coding-earlystop-v1](coding-earlystop-v1/REPORT.md) · [swarm-burst-hard8-v1](swarm-burst-hard8-v1/REPORT.md) · [coding-stagger-v1](coding-stagger-v1/REPORT.md) · [swarm-repair-hard9-v1](swarm-repair-hard9-v1/REPORT.md) · [swarm-strategy-hard10-v1](swarm-strategy-hard10-v1/REPORT.md) · [swarm-width3-hard11-v1](swarm-width3-hard11-v1/REPORT.md) · [swarm-cap12-hard12-v1](swarm-cap12-hard12-v1/REPORT.md) · [mixed-task-v1](mixed-task-v1/REPORT.md) · [swarm-cap12-hard14-v1](swarm-cap12-hard14-v1/REPORT.md) · [swarm-fair-hard22-v1](swarm-fair-hard22-v1/REPORT.md) · [coding-reserve-v1](coding-reserve-v1/REPORT.md) · [coding-reserve-v2](coding-reserve-v2/REPORT.md) · [swarm-fair-hard23-v1](swarm-fair-hard23-v1/REPORT.md)
