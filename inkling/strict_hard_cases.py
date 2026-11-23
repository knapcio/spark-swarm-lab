#!/usr/bin/env python3
"""swarm-hints-hard16-v1: the strict-hard case list for the escalation arms = every (task, seed) case of the shared
first wave (deep4cancel, all segments) that ended without an accepted plan and without an infrastructure fault.
Writes results/swarm-hints-hard16-v1/strict_hard_cases.json (fixed by this rule before any escalation arm runs).
Refuses (exit 1, writes nothing) unless the first wave covers every case of SWARM_HINTS_HARD16_WAVE_PLAN.json exactly
once with a clean row (no infra fault, no 'error'); fault rows are allowed only if a later resume segment reran the case."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAVE = 'swarm-hints-hard16-v1-wave-deep4cancel'
WAVE_PLAN = 'SWARM_HINTS_HARD16_WAVE_PLAN.json'


def expected_keys(plan, data):
    """(task_id, seed) keys of the wave plan, with the same task filter as run_variants.main."""
    tasks = [t for t in data['tasks'] if t['split'] == plan['split']]
    if plan.get('task_ids'):
        tasks = [t for t in tasks if t['id'] in plan['task_ids']]
    if plan.get('numbers_count'):
        tasks = [t for t in tasks if len(t['numbers']) == plan['numbers_count']]
    if len(tasks) != plan['tasks']:
        raise ValueError(f"wave plan expects {plan['tasks']} tasks, corpus has {len(tasks)}")
    return {(t['id'], s) for s in plan['seeds'] for t in tasks}


def select(segments, expected):
    """segments: row lists in segment order. Returns {key: clean row}; raises ValueError on any coverage gap."""
    cases, faults = {}, {}
    for rows in segments:
        for r in rows:
            key = (r['task_id'], r['seed'])
            if key not in expected:
                raise ValueError(f'unexpected case {key}')
            if key in cases:
                raise ValueError(f'case {key} after its clean row (duplicate run)')
            if 'error' in r or r.get('infra', 1):
                faults[key] = r
            else:
                cases[key] = r
                faults.pop(key, None)
    if faults:
        raise ValueError(f'{len(faults)} cases end with an infra fault or error, e.g. {sorted(faults)[0]}')
    missing = expected - cases.keys()
    if missing:
        raise ValueError(f'{len(missing)} of {len(expected)} cases missing, e.g. {sorted(missing)[0]}')
    return cases


def main():
    runs = ROOT / 'runs'
    segs = [WAVE] + [f'{WAVE}-resume{i}' for i in range(1, 10) if (runs / f'{WAVE}-resume{i}' / 'cases.jsonl').exists()]
    plan = json.loads((ROOT / WAVE_PLAN).read_text())
    try:
        expected = expected_keys(plan, json.loads((ROOT / plan['dataset']).read_text()))
        cases = select([[json.loads(line) for line in (runs / d / 'cases.jsonl').read_text().splitlines()] for d in segs],
                       expected)
    except ValueError as exc:
        print(f'strict_hard_cases: first wave incomplete, nothing written: {exc}', file=sys.stderr)
        return 1
    hard = sorted([t, s] for (t, s), r in cases.items() if not r['answered'])
    out = ROOT / 'results' / 'swarm-hints-hard16-v1'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'strict_hard_cases.json').write_text(json.dumps(dict(
        rule='first wave (4 unhinted agents, cancel on accept) ended without an accepted plan, no infra fault',
        wave_cases=len(cases), wave_answered=sum(r['answered'] for r in cases.values()),
        wave_solved=sum(r['solved'] for r in cases.values()), wave_wrong=sum(r['wrong'] for r in cases.values()),
        cases=hard), indent=1) + '\n')
    print(json.dumps(dict(wave_cases=len(cases), strict_hard=len(hard))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
