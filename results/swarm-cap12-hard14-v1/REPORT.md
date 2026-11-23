# Replication: escalation cap 12 vs 8 on a fresh corpus (swarm-cap12-hard14-v1)

Plan [`SWARM_CAP12_HARD14_PLAN.json`](../../SWARM_CAP12_HARD14_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v14 (generator seed 2026112110) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **D roll8strategy** (default): 4 in flight; failures replaced by fresh-seed agents with strategy hints, up to 8.
- **D12 roll12strategy**: identical with up to 12 agents (strictly failure-driven, no time trigger).

## Result

| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D roll8strategy (default, cap 8) | **86** | 0 | 10 | 57,012 | 73 min | 331 / 2336 / 3170 s | 141.5 | 1.65 | 61 | n/a |
| D12 roll12strategy (cap 12) | **88** | 0 | 8 | 66,975 | 91 min | 315 / 3343 / 4425 s | 172.4 | 1.96 | 98 | n/a |

D12 vs D paired: +3 / -1 (p = 0.625). Late rescues in D12 (answered by agents 9-12, which D never runs): 2 (2 correct). Answering slot histogram D12: {0: 27, 1: 19, 2: 21, 3: 16, 4: 2, 5: 0, 6: 0, 7: 1, 8: 1, 9: 0, 10: 1, 11: 0}.

Frozen decision rule: zero_wrong = True, solved_at_least_d_plus_2 = True, late_rescues_at_least_1 = True, adopt_roll12strategy = True

**roll12strategy (cap 12) becomes the default.**

**Mechanism.** Escalation past 8 agents starts only after 8 agents of a case have ended without an accepted plan, so it
cannot change a case that cap 8 answers in the same run; its only effect is to answer cases that would otherwise abstain.
That noise-free count is 2 cases on hard-v12 and 2 on hard-v14, all correct, 0 wrong answers over 192 cases. The rest of the
paired difference is run-to-run noise. Pre-registered pooled hard-v12 + hard-v14 (192 cases): cap 12 173 vs cap 8 167,
paired +9 / -3 (p = 0.15), cap 12 wrong answers 0. Cost on hard-v14:
+17 % server tokens, +24 % arm wall,
1.96 vs 1.65 Wh per solved case (reported, not a gate: the owner's priority is quality; the extra
cost falls only on cases that 8 agents could not solve). Open point: the escalation agents of both arms carry the strategy
hints, whose own gain did not replicate in Fable's pooled replay; the hint recheck is queued and does not affect this cap result.

Files: `run_variants.py` (`roll12strategy`), `inkling/arms.py`, `inkling/report_cap12_hard14.py`, numbers in [report.json](report.json).
