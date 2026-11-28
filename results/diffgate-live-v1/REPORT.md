# Live differential-consensus gate: provisional STOP

Control: 211/216 solved, 5 wrong, 0 unanswered. Gate: 213/216 solved, 3 wrong, 0 unanswered. The frozen wrong and solved checks pass; energy fails (0.985 vs 0.528 GPU Wh per solved case, 1.868x).

The `report.json` decision field records the mechanical STOP. The final interpretation is **provisional STOP / formally inconclusive** because control ran on LAN and the valid gate rerun ran off LAN with an SSH route shim. Wall and energy are not strictly comparable. The unchanged v1 remains rejected operationally; defaults stay R2 + code_elastic.

The paired LAN rerun of both arms remains held in `.runtime/queue/hold/98-diffgate-paired-lan.sh`; it has not run. Invalid outage and SSH-lag reruns are excluded from the published valid-arm result. The swarm is idle by owner decision on 2026-11-27.
