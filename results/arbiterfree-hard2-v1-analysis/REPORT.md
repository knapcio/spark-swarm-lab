# Arbiter-free Nemotron swarm on fresh hard tasks (arithmetic-hard-v2)

Configuration frozen and published (ARBITER_FREE_HARD2_PLAN.json, commit 692d503) BEFORE the 64-task corpus was generated (seed 2026111701; zero overlap with any earlier task). 48 evaluation tasks x 3 seeds = 144 cases. No external verifier in the loop: a Nemotron thinking judge chose the answer; the exact verifier only scored it afterwards.

Policy: 4 short budget-forced agents (8K) -> judge every parsed plan -> first accepted plan wins; if none accepted, 4 deep agents (16K) -> judge -> first accepted; otherwise "no answer".

| Outcome | Cases / 144 |
|---|---:|
| **Solved (accepted plan is correct)** | **96** (67%) |
| Wrong answer (accepted plan is invalid) | **0** |
| No answer (nothing accepted) | 48 |
| Escalated to deep agents | 79 |
| Any agent produced a correct plan (oracle) | 96 |

Solved in stage A: 65; in stage B: 31. Judge decisions: 875 plans judged; accepted & correct 171, accepted & wrong 0, rejected & correct 1, rejected & wrong 703. Mean completion tokens per case (agents + judges): 76,121. 4-number cases solved 68/72, 6-number 28/72. Wall 6320 s, errors [], 0 deadlines, 0 infrastructure failures.

Reading: the swarm never gave a wrong answer and never missed a correct plan that one of its agents found; it answers "I don't know" instead of guessing. The post-hoc estimate on hard-v1 (107/144 with a perfect selector) did not fully carry over: on these fresh tasks the same policy solved 96/144, so part of the earlier number was task-set luck or fitting (hard-v2 may also simply be harder; DeepSeek on the same tasks will tell).
