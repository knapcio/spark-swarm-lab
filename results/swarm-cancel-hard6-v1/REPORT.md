# Cancel the other agents once one plan is accepted (swarm-cancel-hard6-v1)

Plan [`SWARM_CANCEL_HARD6_PLAN.json`](../../SWARM_CANCEL_HARD6_PLAN.json) was frozen and pushed (2376372, code 8f0bc59)
before the fresh corpus arithmetic-hard-v6 (generator seed 2026112102, same rules as hard-v5) was generated (d8bc18e).
Inkling-2-Mini on Spark_01..04, 48 evaluation tasks x seeds 1-2 = 96 paired cases per arm, 4 agents with a 32K budget,
the swarm's own thinking judge, exact verifier for scoring only. Arms ran one after another, each alone on the fleet
(admission, prefix-cache flush, server counters before and after, GPU-rail energy from the 1 Hz logs).

- **A deep4**: 4 agents, all run to the end, first judge-accepted plan in slot order (the previous default).
- **B deep4cancel**: 4 agents; the first judge-accepted plan in time answers the case and the other agents are
  terminated at once (process group killed, the shim closes the upstream stream, SGLang aborts the request in < 0.5 s).
- **C waves2cancel**: agents 0+1 with the B rule; agents 2+3 only if neither was accepted (40 cases at once to keep
  the same ~20 agents per node).

## Result

| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Client tokens/case | Arm wall | Case wall median / p90 | Answer time median / p90 | GPU Wh | Wh per solved | Cancelled / never started agents |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A deep4 | **86** | 0 | 10 | 66,267 | 66,267 | 87 min | 975 / 1578 s | 510 / 1505 s | 165.0 | 1.92 | 0 / 0 |
| B deep4cancel | **83** | 0 | 13 | 44,633 (-33%) | 27,736 | 56 min (-36%) | 384 / 1569 s | 384 / 1569 s | 108.0 (-34%) | 1.3 | 227 / 0 |
| C waves2cancel | **81** | 0 | 15 | 39,250 (-41%) | 33,042 | 59 min (-32%) | 474 / 2689 s | 463 / 2689 s | 106.8 (-35%) | 1.32 | 67 / 151 |

| Paired (task, seed) | Pairs | Wins | Losses | Sign test p |
|---|---:|---:|---:|---:|
| deep4cancel vs deep4 | 96 | 1 | 4 | 0.375 |
| waves2cancel vs deep4 | 96 | 2 | 7 | 0.18 |
| waves2cancel vs deep4cancel | 96 | 3 | 5 | 0.727 |

| Arm | Oracle | One Inkling (agent 0) | Judge verdicts | False accepts | False rejects | Skipped judges | Deadlines | Infra | Shim client cancels | Shim upstream errors | Segments |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A deep4 | 86 | 73 | 340 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| B deep4cancel | 83 | 32 | 131 | 0 | 0 | 0 | 0 | 0 | 227 | 0 | 1 |
| C waves2cancel | 81 | 38 | 116 | 0 | 0 | 4 | 0 | 0 | 67 | 0 | 1 |

Frozen decision rule, applied literally: non_inferior = False, tokens_at_least_15pct_lower = True, wall_not_higher = True, adopt_deep4cancel = False

Server tokens = delta of `sglang:generation_tokens_total` on the four nodes over the arm window (it includes the tokens
of aborted requests; verified with a killed client before the study). Client tokens miss the work of terminated agents,
so the server count is the one that matters. In A they agree exactly (66,267 per case), which
validates the counter. Answer time for A = when the slot-order answer is known (all lower slots finished and judged).

## Verdict: B is accuracy-neutral by mechanism and becomes the default

B cut **server tokens by 33 %**, **arm wall time by 36 %** and
**GPU energy by 34 %** (1.30 vs 1.92 Wh per solved case);
the median case finished in 384 s instead of 975 s. It gave
0 wrong answers.

Honest reading of the pre-registered rule: B solved 83 vs A 86 (paired +1 / -4,
sign test p = 0.38). The frozen non-inferiority margin was B >= A - 2 = 84, so **the margin was
missed by 1** and the frozen decision rule says "not adopted".

The mechanism says the loss is not caused by cancelling:
- **All 4 of B's losses (of 4) are cases where B cancelled nothing.** There B ran the same four agents
  to the end and judged every plan, exactly like A; it simply drew worse samples.
- In every case where B did cancel (82 cases) the answer had already been accepted by the judge, which made
  0 false accepts in 587 verdicts here (and 0 in 330 on hard-v4). Cancelling cannot change
  such a case; B solved all 82 of them.
- **Two identical-configuration runs differ by a few cases.** Same-seed agents do not reproduce across runs (batched
  numerics on the server): of the 157 agents that ran to the end in both A and B with the same seed, only
  27 produced the same number of tokens and **28 (18%) changed outcome**
  (11 solved only in A, 17 only in B). On the 14 cases where B cancelled nothing (so B ran the A policy), 4
  case outcomes flipped. A 3-case difference between two runs of the same policy is ordinary.

Decision (owner, 2026-11-21, on this evidence): **deep4cancel is the default arithmetic swarm policy**; later studies
build on it. A confirmatory check of B against A on a second fresh corpus is part of the next study.

C (waves of 2) solved 81 with 0 wrong (vs A +2 / -7, p = 0.18) at
-41 % server tokens, -32 % arm wall and -35 % energy vs A
(secondary arm; it changes no decision). Waves save the most tokens but stretch the hard cases: its p90 case time
was 2689 s vs 1578 s for A, and it lost more cases than B, so it is not pursued.

One DeepSeek on the same 96 cases (separate plan, run afterwards): see [DEEPSEEK.md](DEEPSEEK.md).

## Abstentions: what more agents could buy

All 23 abstentions (A 10, B 13) had at least one judged and rejected plan. On those cases the other
arm's four fresh agents solved 5 of 23; 9 cases abstained in both arms. So about one abstention in
five is solvable by four more agents; this calibrates the next study (B plus adaptive escalation on a fresh corpus).

## Shim change and cancellation check

`inkling/shim.py` now treats a client that closes its stream as a cancellation: it closes the upstream SGLang stream at
once and counts `shim:client_cancels`, not `shim:upstream_errors` (the watchdog alerts on the latter). Before the study,
on each Spark a streamed thinking completion was killed after 8-10 s: `sglang:num_running_reqs` fell to 0 within 0.5 s,
`client_cancels` = 1, `upstream_errors` = 0, and `generation_tokens_total` included the aborted tokens. The old shim also
freed the server but counted the disconnect as an upstream error. In B, 227 cancellations,
0 upstream errors.

## Exploratory: the same idea for the coding swarm (offline, post hoc)

Replay of the recorded coding swarm (coding-hard-v1, 72 cases, 8 agents of 32K; runs `inkling-coding-hard-v1` + `v1b`)
with [`inkling/sim_coding_early_stop.py`](../../inkling/sim_coding_early_stop.py) ([sim.json](../inkling-coding-early-stop-sim/sim.json)).
No model, sandbox or fleet calls; same data as the 69/72 (first feedback-passing) and 70/72 (executable disproofs)
results, so a hypothesis only. Baseline reproduced exactly (69, 70, 101,889 completion tokens per case). Policy: stop
the case when the first candidate **in time order** passes the public tests and is not disproved by the case's contract;
tokens of agents still generating at the stop are interpolated inside their current request (estimate).

| Variant | Solved /72 | Tokens/case, recorded timeline | Saved | All 8 start at t=0 | Saved | Case wall saved |
|---|---:|---:|---:|---:|---:|---:|
| All 8 to the end (original / disproof rule) | 69 / 70 | 101,889 (+13,273 contract) | | | | |
| Stop at first feedback-passing | 69 | 55,640 | 45 % | 66,600 | 35 % | 61 % / 55 % |
| Stop at first feedback-passing, not disproved | 69 | 56,600 + contract | 44 % (31 % incl. contract) | 67,300 + contract | 34 % (21 %) | 61 % / 55 % |
| Same, not before the contract is ready | 69 | 67,300 + contract | 34 % (21 %) | 80,600 + contract | 21 % (8 %) | 49 % / 38 % |

- Every early-stop variant gives **69/72**: original accuracy kept, the disproof gain (70) lost. Lost
  `eva-date_diff_ymd-s3` and `eva-monthly_occurrences-s1` (the first finisher passed the public tests, was not disproved
  and failed the hidden holdout); gained `eva-shell_words-s1` (already fixed by disproofs) and `eva-shell_words-s2`.
- About a third fewer tokens if all agents start together; the contract call (13.3K tokens, median 622 s) eats much of it.
- Unlike arithmetic, where acceptance is an independent judge with 0 false accepts, the coding stop signal lets wrong
  candidates through, and the fastest finisher is not safer. Expected live outcome: 69 for about a third fewer tokens,
  not 70 for less. Needs a frozen plan on fresh tasks before any claim.

## Files

Runner `run_variants.py` (`deep4cancel`, `waves2cancel`, `--policy`; the cancellable executor lives here because
`run_benchmark.py` is hash-pinned by earlier frozen plans), arm driver `inkling/arms.py`, report
`inkling/report_cancel_hard6.py`, accounting per arm in `runs/swarm-cancel-hard6-v1-*/arm_accounting.json` (not in git),
numbers in [report.json](report.json).
