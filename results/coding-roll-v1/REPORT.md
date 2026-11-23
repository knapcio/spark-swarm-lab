# Coding swarm: replace failed agents instead of a timed second wave (coding-roll-v1)

Plans `CODING_ROLL_S_PLAN.json`, `CODING_ROLL_R4_PLAN.json` and `CODING_ROLL_R2_PLAN.json` were frozen and pushed before any
call with seeds 13-15 on coding-hard-v1 (24 evaluation tasks x 3 fresh seeds = 72 cases, agent seed offset 4700).
Idea 1 of Fable's round-2 list (IDEAS-swarm-round2-fable.md). All arms use early stop at the first proposal that passes
the public tests; each ran alone on the fleet (Inkling-2-Mini x4, mem fraction 0.75, 20 agents per node).

## Result

| Arm | Solved /72 | Wrong | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Stop median / p90 | Agents started per case |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S: early stop + stagger 4+4 at 300 s (default) | **65** | 5 | 50,750 | 53 min | 99.03 | 1.52 | 340 / 1056 s | 6.11 |
| R4: replace failures, 4 in flight | **69** | 2 | 38,206 (-25 %) | 47 min | 83.79 | 1.21 | 362 / 848 s | 4.18 |
| R2: replace failures, 2 in flight | **71** | 1 | 24,275 (-52 %) | 49 min | 71.83 | 1.01 | 405 / 1089 s | 2.15 |

R4 vs S paired: +7 / -3 (p = 0.34). R2 vs S paired: +6 / -0 (p = 0.031). 

Frozen decision rule (R2 if solved >= S - 2 and tokens <= 0.70 x S; else R4 if solved >= S - 2 and tokens <= 0.85 x S; else S): adopt **R2**.

**Mechanism.** Tokens: under early stop every agent still running when one passes the public tests is wasted work;
R2 keeps 2 agents in flight and starts the next only after a failure, so it starts 2.15 agents per case instead of 6.11.
Accuracy: a "wrong" coding answer passed the public tests but fails the hidden ones, which the swarm cannot see. In S,
4 of the 5 wrong answers were the first of 4 racing agents to pass, after 128-293 s; with fewer agents racing, a quick
answer that only happens to pass is less likely to win, and R2 answered 4 of those 5 cases correctly (stop 228-905 s).
R2 lost no case that S solved (+6 / -0). The price is latency: median stop 405 s vs 340 s, p90 about the same.
**R2 (failure-driven replacement, 2 in flight) becomes the coding default.**

Files: `run_coding_earlystop.py` (`rolling`), `inkling/coding_arms.py`, `inkling/report_coding_roll.py`, numbers in [report.json](report.json).
