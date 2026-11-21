# Coding swarm: stop at the first proposal that passes the public tests (coding-earlystop-v1)

Plans [`CODING_EARLYSTOP_STOP_PLAN.json`](../../CODING_EARLYSTOP_STOP_PLAN.json) and
[`CODING_EARLYSTOP_FULL_PLAN.json`](../../CODING_EARLYSTOP_FULL_PLAN.json) were frozen and pushed (669665e) before any call
with seeds 4-6 on coding-hard-v1 (24 evaluation tasks x 3 fresh seeds = 72 cases, agent seed offset 1700, so every
agent sample is new). Inkling-2-Mini on Spark_01..04 (mem fraction 0.75), 8 independent 32K `code_xl` agents per case,
20 agents per node, each arm alone on the fleet with server-side token counting and GPU-rail energy. Proposals are
graded in the CPU sandbox on public feedback cases (used by the controller) and hidden holdout cases (scoring only).

- **F**: all 8 agents run to the end; answer = first agent in slot order whose code passes all feedback cases
  (the rule of inkling-coding-hard-v1).
- **E**: the first proposal in time that passes all feedback cases ends the case; the other agents are terminated
  (shim closes the stream, SGLang aborts), queued ones never start.

## Result

| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy | Wh per solved | Cancelled / never started agents |
|---|---:|---:|---:|---:|---:|---:|
| F: 8 agents to the end (slot-order first passing) | **66** | 99,752 | 96 min | 180.69 Wh | 2.74 | 0 / 0 |
| E: stop at first passing in time | **69** | 62,790 (-37 %) | 61 min (-36 %) | 116.57 Wh | 1.69 | 495 / 0 |

E vs F paired: +5 / -2 (p = 0.45). Inside F (same proposals, no generation noise): time-order pick 71 vs slot-order pick 66 (selection effect +5). F oracle 72, One Inkling (agent 0) 62.

Frozen decision rule: selection_effect_at_least_minus_1 = True, tokens_at_most_80pct = True, wall_lower = True, adopt_early_stop = True

- Early stop solved **69/72** vs 66 for the full run (paired +5 / -2, p = 0.45) at
  **37 % fewer server tokens**, **36 % less wall time** and
  36 % less GPU energy; the median case stopped after 343 s.
- The noise-free part: inside F, on the very same proposals, taking the first passing proposal in **time** order
  solves 71 vs 66 for slot order (+5). The fastest passing proposal is the better pick here (the offline
  replay of seeds 1-3 found no difference, 69 vs 69); the rest of E vs F is run-to-run noise.
- Context: F's oracle (any agent passing feedback and holdout) is 72/72; One Inkling (agent 0) 62/72.

Frozen rule: early stop is adopted if the selection effect inside F >= -1, E tokens <= 0.80 x F and E wall < F:
selection_effect_at_least_minus_1 = True, tokens_at_most_80pct = True, wall_lower = True, adopt_early_stop = True.

**Early stop becomes the default for the Inkling coding swarm.**

Files: `run_coding_earlystop.py` (runner), `run_coding_agents.py` (baseline, unchanged), `inkling/coding_arms.py`
(arm driver), `inkling/report_coding_earlystop.py`, numbers in [report.json](report.json).
