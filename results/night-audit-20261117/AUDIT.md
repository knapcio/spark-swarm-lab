# Independent audit, night 2026-11-16/17

Read-only. Counts were recomputed from raw event JSONL and bugbench `attempts.jsonl` + event logs. Arithmetic plans were re-verified with a separate replay. Times are UTC.

## 1. confirm-v2: VERIFIED
- 144 vs 93 (budget-matched 142); single runs 985/1,152 vs 155/576. Exact; 0 row mismatches.
- **CONCERN:** 413/576 baseline calls hit 8,192 tokens and 0 solved. Baseline calls that finished solved 155/163. On hard tasks: 461/576 truncated, 0 solved.

## 2. Hard tasks and deep agents: VERIFIED, one semantic DISCREPANCY
- Short swarm 81 vs 57; deep 4 = 99; deep 8 = 111. The 4/6-number split and the +2.8..+22.9 pp interval are exact.
- **DISCREPANCY:** the replay counts a plan as solved once the target first appears. `eva-hf7d6ff4cf98 s1 a3` reaches 867 at move 4, then a 5th move gives 860.
  - Strictly scored: 98 / 110 / single 211.
  - This is the only such row among 2,492 arithmetic solves.
- **Hung row:** `eva-h4a519b4f65d s1 a2` has a complete trace (`run_end` 21:15:00Z, complete, 11,539 tokens) and its plan re-verifies. It is not pivotal: 6 other agents solved the case.

## 3. depth-hard-dev: VERIFIED
All rates, token means and the subset table are exact.

## 4. DeepSeek: VERIFIED, CONCERNS
- Results: v2 144/144; hard k1 98.5, any-of-2 107; 81/288 calls hit 8,192, 0 solved.
- The discarded diagnostic rows solved 23/32; the rerun solved 19 of the same rows, so it did not favour DeepSeek.
- **CONCERN:** the stream plan kept `agent_wall_deadline_seconds: 480`. That is the cutoff the 32K erratum calls "contrary to the study rules". It never fired, but the slowest call took 427 s.
- **CONCERN:** the 32K rerun has 7/144 rows.

## 5. Judge: VERIFIED
- The confusion matrices and the selection table reproduce exactly. Truth labels match the replay.
- The prompt (sha matches 91e3f54) holds only the numbers, the target and the raw plan JSON: no verdict, no replayed state.
- **CONCERN:** no frozen judge plan; judge-selected equals oracle only at k≥2 (v2 at k=1: 121 vs 123); the prompt states the lenient first-appearance rule.

## 6. Coding: VERIFIED, CONCERNS
- Plain 4/6/9/9, forced 22..28, deep 22/30/32/34, deep-8 expected curve and 37. All reproduce. Selection reads only `feedback_pass` (`run_coding_agents.py:74`).
- **CONCERNS:**
  - Plain agents parsed only 14/288.
  - Oracle vs selected: forced 38 vs 28, deep-8 45 vs 37.
  - Deep 4 vs forced 8: discordant pairs 7 vs 1, exact McNemar p=0.07.
  - The extension's 4 agents alone score 38, above the pooled 37.
  - The deep agent was not selected on any coding dev split.

## 7. bugbench eval18: VERIFIED counts, CONCERNS
- v1 (35 complete rows) + v2 (109) give exactly 144 ids: S1 18, S3 26, T3 26, V3 28. Oracle: 18/26/27/29.
- 2 reruns, both T3 SSH faults that happened before `selection_frozen`. Counted as failures, T3 = 24.
- No prompt references hidden files or probes. Selection always precedes hidden grades. 118 selections re-derived with 0 mismatches. The 126 manifest hashes match.
- **CONCERNS:**
  - The continuation amendment (84be0c7, 22:48:58Z) was written after v1 outcomes were visible. It omits v2's higher concurrency and round-robin grading.
  - The manifest `grader_sha256` is stale.
  - T3's peer cross-validation score never varied. V3's reviewer changed 1 pick; without it V3 = 27.
  - V3 vs S3: discordant 3 vs 1, p=0.63.
  - `bugbench/runs/` is untracked.

## 8. Protocol timing: VERIFIED
Every freeze commit precedes the first call. Every run's `plan_sha256` equals the committed blob.

| Plan | Freeze | First call | Post-freeze edits |
|---|---|---|---|
| CONFIRM_V2 | 10:41:18 | 10:42:37 | ae4c6ca protocol-id erratum (irrelevant) |
| CONFIRM_HARD | 10:41:18 | 11:58:38 | none |
| DEPTH_HARD_DEV | 13:34:07 | 13:34:26 | none |
| CONFIRM_HARD_LONG | 14:17:23 | 14:22:56 | none |
| …_LONG_EXT | 18:35:50 | 20:44:44 | none |
| CODING_HARD_EVAL | 14:22:51 | 18:03:01 | none (PROPOSED→FROZEN was status only) |
| CODING_HARD_LONG / _EXT | 23:14:56 / 00:36:23 | 23:15:02 / 00:36:28 | none |
| DEEPSEEK_FRESH | 11:12:29 | 15:37:15 | hard tasks replaced by HARD_STREAM (16:17:39, run 16:17:49): transport and concurrency 4→8, after 16 hard cases were seen |
| DEEPSEEK_HARD_32K | 21:03:45 | 02:36:56 | deadline 480→3,600 s after 8/8 kills; v2 run |
| DEEPSEEK_CODING | 01:53:24 | 02:36:58 | none; no plan hash recorded |
| bugbench EVAL_PLAN | 20:53:35 | 20:53:38 | 84be0c7 continuation (§7) |

The approximate times written into plan notes ("~11:50", "~21:55", "~23:55") fall after the actual commits, so they are unreliable.

## 9. Deadlines: VERIFIED
- No reported run has a `deadline` row.
- `deepseek-hard-32k-v1` has 8 deadline rows; it is diagnostic and excluded.
- `deepseek-fresh-v1` had one 210 s HTTP timeout, which led to the rerun.
- Latent caps never fired: 480 s for DeepSeek, 2,400 s for coding, and a 120 s idle limit.

## Five caveats an article must state
1. The 8K baseline fails almost only through truncation: 72% of v2 calls were cut off and all of them failed, while 95% of finished calls were correct. Budget forcing is the main effect.
2. Deep agents, the extensions, the judge and deep coding were designed after evaluation results were known, and they reuse those sets. The arithmetic extension aimed explicitly at "exceed DeepSeek 107", so these results are exploratory.
3. DeepSeek is handicapped. 28% of its hard calls were truncated, and the 32K rerun is incomplete. Its 480 s cap did not fire only by luck.
4. The samples are small and clustered. Coding deep-4 vs forced-8 has p≈0.07, and the bugbench swarms are indistinguishable from each other. T3's cross-validation and V3's reviewer almost never acted. Gains over S1 cost about 8–12x the calls.
5. The arithmetic verifier counts a plan as solved once the target first appears; strictly scored, 111 becomes 110. bugbench's continuation rule was written after v1 outcomes were visible.
