# swarm-baseline-hard33-v1

Descriptive baseline of roll12fair; no adoption decision. The frozen plan is `SWARM_BASELINE_HARD33_PLAN.json` (SHA256 `dc1f8d4575b9c2be9ff1c0b5701b6f1805fd0c24d69cf9157fea6f66178bd06f`).

| cases | solved | wrong | unanswered | generated tokens | wall s | GPU Wh | Wh/solved |
|---|---|---|---|---|---|---|---|
| 96 | 85 | 0 | 11 | 7,557,492 | 4401.8 | 151.56 | 1.783 |

Evidence: `runs/swarm-baseline-hard33-v1-roll12fair` (arm_accounting.json, metadata.json, cases.jsonl, final runner log summary). Input hashes and per-case outcomes are in `report.json`. Runner exit 0; recorded idle after completion; 0 infrastructure failures and 0 deadlines.

Hard-v33 is the full valid LAN rerun; the earlier outage-aborted run is excluded. Its wasted work is not included in these valid-run metrics. Raw run directories remain local. Metrics use the recorded server counters and GPU energy accounting; these baselines do not establish a new default.
