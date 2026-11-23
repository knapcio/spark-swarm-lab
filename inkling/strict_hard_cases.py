#!/usr/bin/env python3
"""swarm-hints-hard16-v1: the strict-hard case list for the escalation arms = every (task, seed) case of the shared
first wave (deep4cancel, all segments) that ended without an accepted plan and without an infrastructure fault.
Writes results/swarm-hints-hard16-v1/strict_hard_cases.json (fixed by this rule before any escalation arm runs)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAVE = 'swarm-hints-hard16-v1-wave-deep4cancel'


def main():
    runs = ROOT / 'runs'
    segs = [WAVE] + [f'{WAVE}-resume{i}' for i in range(1, 10) if (runs / f'{WAVE}-resume{i}' / 'cases.jsonl').exists()]
    cases = {}
    for d in segs:
        for line in (runs / d / 'cases.jsonl').read_text().splitlines():
            r = json.loads(line)
            if 'error' not in r and not r['infra']:
                cases[(r['task_id'], r['seed'])] = r
    hard = sorted([t, s] for (t, s), r in cases.items() if not r['answered'])
    out = ROOT / 'results' / 'swarm-hints-hard16-v1'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'strict_hard_cases.json').write_text(json.dumps(dict(
        rule='first wave (4 unhinted agents, cancel on accept) ended without an accepted plan, no infra fault',
        wave_cases=len(cases), wave_answered=sum(r['answered'] for r in cases.values()),
        wave_solved=sum(r['solved'] for r in cases.values()), wave_wrong=sum(r['wrong'] for r in cases.values()),
        cases=hard), indent=1) + '\n')
    print(json.dumps(dict(wave_cases=len(cases), strict_hard=len(hard))))


if __name__ == '__main__':
    main()
