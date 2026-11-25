| Arm | Solved | Wrong | No answer | Server tokens/case | Solver tokens/case | Judge tokens/case | Wall | GPU Wh | Wh per solved | Stop median / p90 | Agents started/case |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R2, public tests (default) | **69**/72 | 3 | 0 | 22,562 | 14,370 | 0 | 2,057 s | 53.44 | 0.77 | 359 / 835 s | 2.1 |
| R2, no tests: own tests | **68**/72 | 1 | 3 | 52,296 | 39,549 | 0 | 3,989 s | 112.17 | 1.65 | 797 / 1,488 s | 2.65 |
| R2, no tests: judge | **70**/72 | 2 | 0 | 54,699 | 30,185 | 14,797 | 4,047 s | 120.24 | 1.72 | 1,082 / 1,890 s | 2.22 |

| Arm | Finished agents | Parsed | Accepted | Accepted, correct | Accepted, wrong | Rejected, correct | Invalid own tests | Judge unparsed | Late decisions (excluded) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R2, public tests (default) | 80 | 80 | 72 | 69 | 3 | 0 | 0 | 0 | 0 |
| R2, no tests: own tests | 123 | 96 | 69 | 68 | 1 | 22 | 1 | 0 | 0 |
| R2, no tests: judge | 88 | 88 | 72 | 70 | 2 | 3 | 0 | 0 | 0 |

Judge verdicts (R2, no tests: judge; budget 16,384 thinking + 2,048 answer, 2 calls): 88 parsed, forced after the thinking cap: 45 (51.1 %); unparseable results (not in the share): 0.

Budgets: the solver budget is identical in all arms. The judge arm adds, per parsed proposal, up to 2 judge calls and up to 18,432 completion tokens (16,384 thinking + 2,048 for a forced verdict) on the same server; they are included in its server and client tokens and GPU Wh and shown separately as judge tokens per case (completed judge calls of cancelled agents included). A forced verdict is one given after the judge's thinking hit its cap; the forced-verdict share is reported per arm.

Decision timing: the public-tests arm is the unchanged default path of every earlier coding study: it decides at the first feedback pass observed when a worker exits, i.e. after the hidden holdout grading that runs inside the worker. The no-tests arms decide BEFORE hidden grading: the winner is the accepted proposal with the earliest recorded decision within the agent deadline, and hidden grading runs afterwards for scoring only.

R2, no tests: own tests vs public tests, paired on 72 cases: solved +3 / -4 (p = 1); answered +0 / -3 (p = 0.25).
R2, no tests: judge vs public tests, paired on 72 cases: solved +3 / -2 (p = 1); answered +0 / -0 (p = 1).
