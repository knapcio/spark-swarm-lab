#!/usr/bin/env python3
"""bugbench evaluation report: pooled eval18-v1 (completed attempts) + eval18-v2 (continuation)."""
import collections, json, random, sys
from pathlib import Path

runs = [Path(p) for p in sys.argv[1:-1]]
out = Path(sys.argv[-1])
rows = {}
infra = []
for run in runs:
    for line in open(run / 'attempts.jsonl'):
        d = json.loads(line)
        aid = d.get('attempt_id') or f"{d['case_id']}__{d['policy']}__s{d['seed']}"
        if d['status'] == 'infrastructure_fault':
            infra.append((run.name, aid)); continue
        rows[aid] = d  # a later run's rerun of an infra-faulted attempt replaces nothing completed
policies = ['S1', 'S3', 'T3', 'V3']
names = {'S1': 'single navigator', 'S3': '8 independent navigators + vote', 'T3': '8 test-first agents + cross-validation by peers’ tests', 'V3': '8 independent navigators + model reviewer'}
stat = {}
by_case = collections.defaultdict(dict)
for p in policies:
    rs = [d for d in rows.values() if d['policy'] == p]
    passed = [d for d in rs if (d.get('selected_grade') or {}).get('status') == 'passed']
    oracle = [d for d in rs if (d.get('oracle') or {}).get('any_passed')]
    stat[p] = dict(n=len(rs), passed=len(passed), oracle=len(oracle),
                   calls=sum(d['budget']['calls'] for d in rs) / max(1, len(rs)),
                   tokens=sum(d['budget']['completion_tokens'] for d in rs) / max(1, len(rs)),
                   no_candidate=sum(not (d.get('selection') or {}).get('candidates') for d in rs))
    for d in rs:
        by_case[d['case_id']][(p, int(d['seed']))] = (d.get('selected_grade') or {}).get('status') == 'passed'

def paired(a, b, draws=4000):
    cases = sorted(by_case)
    diffs = {c: [by_case[c].get((a, s), False) - by_case[c].get((b, s), False) for s in (1, 2)] for c in cases}
    rng = random.Random(0); stats = []
    for _ in range(draws):
        v = [x for c in (rng.choice(cases) for _ in cases) for x in diffs[c]]
        stats.append(sum(v) / len(v))
    stats.sort()
    return stats[int(.025 * draws)], stats[int(.975 * draws) - 1]

lines = ['# bugbench evaluation: 18 new cases x 2 seeds', '',
         'Six original multi-module projects (900-1,500 lines, larger than one 16K context), three planted bugs each (easy/medium/hard), frozen before any model call. '
         'Agents see the buggy project and a user bug report, never the hidden probes. Selection is arbiter-free (public tests, agent-written tests, votes, model reviews); '
         'the selected patch receives exactly one hidden grade. "Oracle" = some candidate patch would have passed (hindsight upper bound, never used for selection).', '',
         '| Policy | Fixed (hidden grade) | Oracle any | No patch | Mean calls | Mean completion tokens |', '|---|---:|---:|---:|---:|---:|']
for p in policies:
    s = stat[p]
    lines.append(f"| {p} — {names[p]} | **{s['passed']}/{s['n']}** ({s['passed']/max(1,s['n']):.0%}) | {s['oracle']} | {s['no_candidate']} | {s['calls']:.1f} | {s['tokens']:,.0f} |")
lines += ['', 'Paired differences vs S1 (case-cluster bootstrap 95% interval):']
for p in ('S3', 'T3', 'V3'):
    lo, hi = paired(p, 'S1'); lines.append(f'- {p} − S1: {lo:+.0%} to {hi:+.0%}')
lines += ['', '| Case | ' + ' | '.join(policies) + ' |', '|---|' + '---:|' * len(policies)]
for c in sorted(by_case):
    lines.append(f'| {c} | ' + ' | '.join(''.join('✓' if by_case[c].get((p, s)) else '·' for s in (1, 2)) for p in policies) + ' |')
lines += ['', f'Infrastructure faults (excluded, rerun in the continuation): {len(infra)} {infra}. Two runs are pooled per the frozen plan amendment; attempts are independent.']
out.mkdir(parents=True, exist_ok=True)
(out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
(out / 'results.json').write_text(json.dumps(dict(stat=stat, infra=infra), indent=2) + '\n')
print('\n'.join(lines))
