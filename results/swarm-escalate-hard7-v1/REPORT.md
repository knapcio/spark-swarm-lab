# Escalation: spend the cancel savings on the hard cases (swarm-escalate-hard7-v1)

Plan [`SWARM_ESCALATE_HARD7_PLAN.json`](../../SWARM_ESCALATE_HARD7_PLAN.json) was frozen and pushed (1409067) before the
fresh corpus arithmetic-hard-v7 (generator seed 2026112103, same rules as v5/v6) was generated (168e423). Inkling-2-Mini
on Spark_01..04, 48 evaluation tasks x seeds 1-2 = 96 paired cases per arm, agents with a 32K budget, the swarm's own
thinking judge (exact verifier only scores). Arms ran one after another, each alone on the fleet, with server-side token
counting and GPU-rail energy, in the order B, B+, A.

- **B deep4cancel** (default since [hard6](../swarm-cancel-hard6-v1/REPORT.md)): 4 agents; the first judge-accepted
  plan answers and the other agents are terminated.
- **B+ roll8cancel**: as B, but every agent that ends without an accepted plan is replaced at once by a fresh-seed agent
  on the same node (4 in flight), up to 8 agents per case.
- **A deep4** (reference): 4 agents, all to the end.

## Result

| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 | GPU Wh | Wh per solved | Cancelled / escalation agents |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B deep4cancel (default) | **79** | 0 | 17 | 43,976 | 55 min | 366 / 1611 s | 103.7 | 1.31 | 217 / 0 |
| B+ roll8cancel (escalation, max 8) | **90** | 0 | 6 | 53,641 (+22 % vs B) | 71 min (+30 % vs B) | 368 / 1845 s | 133.4 | 1.48 | 252 / 57 |
| A deep4 (reference) | **82** | 0 | 14 | 66,592 (+51 % vs B) | 90 min (+64 % vs B) | 1050 / 1538 s | 167.1 | 2.04 | 0 / 0 |

| Paired (task, seed) | Pairs | Wins | Losses | Sign test p |
|---|---:|---:|---:|---:|
| roll8cancel vs deep4cancel | 96 | 12 | 1 | 0.00342 |
| roll8cancel vs deep4 | 96 | 9 | 1 | 0.0215 |
| deep4cancel vs deep4 | 96 | 5 | 8 | 0.581 |
| pooled_v6_v7_deep4cancel vs deep4 | 192 | 6 | 12 | 0.238 |

Escalation inside B+: 17 cases escalated (57 extra agents; 4 of them were then solved by one of the first four), 7 cases answered by an escalation agent, of which **6 strict rescues** (all first four had already failed), 6 correct.

Frozen decision rule: zero_wrong = True, strict_rescues_at_least_2 = True, tokens_at_most_reference = True, wall_below_reference = True, reference = A deep4, adopt_roll8cancel = True
Owner goal (B+ solved >= A solved): True

## Reading

- **B+ solved 90/96 with 0 wrong**, vs B 79 (paired +12 / -1, p = 0.0034) and A 82
  (+9 / -1, p = 0.021). The mechanism count, free of run-to-run noise: 6 cases were answered
  by an escalation agent after all of the first four had failed (6 of them correct); without escalation those
  cases are abstentions in the same run. The rest of the gap to B is run-to-run generation noise (hard-v6: two runs of
  one policy differ by about 4 cases).
- Cost: B+ used 53,641 server tokens per case (+22 % vs B,
  -19 % vs A), 71 min of arm wall (+30 % vs B,
  -21 % vs A) and 1.48 Wh per solved case (B 1.31, A 2.04).
  Escalation ran in 17 cases (57 extra agents); the extra wall time comes from the escalated hard
  cases, which run up to twice as long as an abstention in B.
- Second-corpus check of B vs A (noise replication): +5 / -8 (p = 0.58); pooled hard-v6 + v7, 192 cases:
  +6 / -12 (p = 0.24). Again **all 8 of B's
  8 losses are cases where B cancelled nothing** (it ran A's policy there and drew worse samples), so
  cancellation cannot be their cause. The direction repeated on both corpora, though, which we note openly; the pooled
  difference is not significant, and B+ (which contains B) is above A on this corpus.

One DeepSeek on the same 96 cases (separate plan, run afterwards): see [DEEPSEEK.md](DEEPSEEK.md).

## Decision

Frozen rule: B+ replaces B if 0 wrong, >= 2 strict rescues, server tokens per case <= A and arm wall < A.
zero_wrong = True, strict_rescues_at_least_2 = True, tokens_at_most_reference = True, wall_below_reference = True, reference = A deep4, adopt_roll8cancel = True.

**B+ becomes the default arithmetic swarm policy.**
Owner goal (B+ solved >= A solved, 0 wrong, tokens <= A, wall < A): solved 90 vs 82, tokens
53,641 vs 66,592, wall 71 vs 90 min.

Files: runner `run_variants.py` (`roll8cancel`), arm driver `inkling/arms.py`, report `inkling/report_escalate_hard7.py`,
numbers in [report.json](report.json).
