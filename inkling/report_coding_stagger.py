#!/usr/bin/env python3
"""Report for coding-stagger-v1: S (early stop, 4 agents first, 4 more after 300 s or when the first four failed) vs
E (early stop, all 8 agents at once; the coding default) on coding-hard-v1, fresh seeds 7-9.
Writes results/coding-stagger-v1/{REPORT.md, report.json, tables.md}."""
import json
import statistics

from report_coding_earlystop import RUNS, ROOT, accounting, stop_arm
from report_hard4 import sign_test

OUT = ROOT / 'results' / 'coding-stagger-v1'


def arm(name):
    cases, acct = stop_arm(name), accounting(name)
    stops = sorted(c['stop_seconds'] for c in cases.values() if c['stop_seconds'] is not None)
    rows = json.loads((RUNS / name / 'summary.json').read_text())
    second = {(r['task_id'], r['seed']) for r in rows if r['agent'] >= 4}
    return cases, dict(solved=sum(c['solved'] for c in cases.values()), answered=sum(c['answered'] for c in cases.values()),
                       tokens_per_case=round(acct['server_tokens'] / len(cases)), wall=acct['wall'], wh=acct['wh'],
                       cancelled=sum(c['cancelled'] for c in cases.values()), never_started=sum(c['never_started'] for c in cases.values()),
                       second_wave_cases=len(second), stop_median=round(statistics.median(stops)) if stops else None,
                       stop_p90=round(stops[int(.9 * len(stops))]) if stops else None, upstream_errors=acct['upstream_errors'])


def main():
    cs, s = arm('coding-stagger-v1-s44')
    ce, e = arm('coding-stagger-v1-e8')
    keys = sorted(cs)
    assert set(keys) == set(ce)
    w = sum(cs[k]['solved'] and not ce[k]['solved'] for k in keys)
    l = sum(ce[k]['solved'] and not cs[k]['solved'] for k in keys)
    res = dict(stagger=s, all8=e, paired=dict(wins=w, losses=l, p=sign_test(w, l)),
               ratios=dict(tokens=round(s['tokens_per_case'] / e['tokens_per_case'], 3), wall=round(s['wall'] / e['wall'], 3),
                           energy=round(s['wh'] / e['wh'], 3) if s['wh'] and e['wh'] else None))
    res['decision'] = dict(tokens_at_most_85pct=res['ratios']['tokens'] <= .85, solved_at_least_e_minus_2=s['solved'] >= e['solved'] - 2,
                           wall_at_most_110pct=res['ratios']['wall'] <= 1.10)
    res['decision']['adopt_stagger'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    row = lambda n, a: (f"| {n} | **{a['solved']}** | {a['tokens_per_case']:,} | {a['wall'] / 60:.0f} min | {a['wh']} Wh | "
                        f"{a['wh'] / max(1, a['solved']):.2f} | {a['stop_median']} / {a['stop_p90']} s | {a['second_wave_cases']} | {a['cancelled']} / {a['never_started']} |")
    md = ('| Arm | Solved /72 | Server tokens/case | Arm wall | GPU energy | Wh per solved | Stop median / p90 | Cases with agents 5-8 | Cancelled / never started |\n'
          '|---|---:|---:|---:|---:|---:|---:|---:|---:|\n' + row('E: all 8 at once (default)', e) + '\n' + row('S: 4 first, 4 more after 300 s', s) + '\n'
          f"\nS vs E paired: +{w} / -{l} (p = {res['paired']['p']:.2g}); S/E tokens {res['ratios']['tokens']}, wall {res['ratios']['wall']}, energy {res['ratios']['energy']}.\n\n"
          'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
    (OUT / 'tables.md').write_text(md)
    verdict = ('**The staggered start becomes the coding default.**' if res['decision']['adopt_stagger'] else
               '**All 8 agents at once stays the coding default** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
    (OUT / 'REPORT.md').write_text(f"""# Coding swarm: start 4 agents, add 4 only if needed (coding-stagger-v1)

Plans [`CODING_STAGGER_S44_PLAN.json`](../../CODING_STAGGER_S44_PLAN.json) and [`CODING_STAGGER_E8_PLAN.json`](../../CODING_STAGGER_E8_PLAN.json)
were frozen and pushed before any call with seeds 7-9 on coding-hard-v1 (24 evaluation tasks x 3 fresh seeds = 72 cases,
agent seed offset 2700). Both arms use the coding default since [coding-earlystop-v1](../coding-earlystop-v1/REPORT.md):
the first proposal passing all public feedback cases ends the case. Inkling-2-Mini, mem fraction 0.75, 20 agents per
node, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **E**: all 8 agents queued at once.
- **S**: agents 1-4 first; agents 5-8 start only if no proposal has passed 300 s after the case's first agent started,
  or as soon as all of the first four have finished without a pass.

## Result

{md}
{verdict}

Files: `run_coding_earlystop.py` (`stagger`), `inkling/coding_arms.py`, `inkling/report_coding_stagger.py`,
numbers in [report.json](report.json).
""")
    print(md)


if __name__ == '__main__':
    main()
