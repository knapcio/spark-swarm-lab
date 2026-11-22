#!/usr/bin/env python3
"""Report for MIXED_TASK_PLAN.json (mixed-task-v1): arithmetic + coding default swarms served together (M) vs one after the
other alone (Sa then Sc). Writes results/mixed-task-v1/{REPORT.md, report.json}."""
import json

from report_cancel_hard6 import RUNS, ROOT, paired
from report_hard4 import sign_test

OUT = ROOT / 'results' / 'mixed-task-v1'


def arith(d):
    return {(r['task_id'], r['seed']): r for r in map(json.loads, (d / 'cases.jsonl').read_text().splitlines())}


def coding(d):
    return {(c['task_id'], c['seed']): c for c in json.loads((d / 'cases.json').read_text())}


def acct(d):
    a = json.loads((d / 'arm_accounting.json').read_text())
    return dict(wall=a['runner_wall_seconds'], wh=(a['energy'] or {}).get('total_wh'), tokens=a['server']['total']['generation_tokens'],
                upstream_errors=a['server']['total']['shim_upstream_errors'])


def main():
    M, Sa, Sc = RUNS / 'mixed-task-v1-M', RUNS / 'mixed-task-v1-Sa', RUNS / 'mixed-task-v1-Sc'
    am, aa, cm, ca = arith(M / 'arith'), arith(Sa), coding(M / 'coding'), coding(Sc)
    xm, xa, xc = acct(M), acct(Sa), acct(Sc)
    mixed_runners = json.loads((M / 'arm_accounting.json').read_text())['runners']
    cw = sum(cm[k]['solved'] and not ca[k]['solved'] for k in cm)
    cl = sum(ca[k]['solved'] and not cm[k]['solved'] for k in cm)
    res = dict(arith=dict(mixed=sum(r['solved'] for r in am.values()), alone=sum(r['solved'] for r in aa.values()),
                          wrong_mixed=sum(r['wrong'] for r in am.values()), wrong_alone=sum(r['wrong'] for r in aa.values()), paired=paired(am, aa)),
               coding=dict(mixed=sum(c['solved'] for c in cm.values()), alone=sum(c['solved'] for c in ca.values()),
                           paired=dict(pairs=len(cm), wins=cw, losses=cl, p=sign_test(cw, cl))),
               wall=dict(mixed=xm['wall'], sequential=xa['wall'] + xc['wall'], arith_alone=xa['wall'], coding_alone=xc['wall'],
                         mixed_arith_done=mixed_runners['arith']['wall'], mixed_coding_done=mixed_runners['coding']['wall']),
               energy=dict(mixed=xm['wh'], sequential=round(xa['wh'] + xc['wh'], 1)),
               tokens=dict(mixed=xm['tokens'], sequential=xa['tokens'] + xc['tokens']),
               upstream_errors=dict(mixed=xm['upstream_errors'], arith=xa['upstream_errors'], coding=xc['upstream_errors']))
    res['decision'] = dict(wall_at_most_95pct=xm['wall'] <= 0.95 * (xa['wall'] + xc['wall']),
                           energy_not_higher=xm['wh'] <= xa['wh'] + xc['wh'],
                           arith_within_noise=res['arith']['mixed'] >= res['arith']['alone'] - 2 and res['arith']['wrong_mixed'] == 0,
                           coding_within_noise=res['coding']['mixed'] >= res['coding']['alone'] - 2)
    res['decision']['recommend_mixed'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    w, e, A, C = res['wall'], res['energy'], res['arith'], res['coding']
    md = (f"| | Mixed (M) | One after the other (Sa + Sc) |\n|---|---:|---:|\n"
          f"| Arithmetic solved /96 (wrong) | **{A['mixed']}** ({A['wrong_mixed']}) | **{A['alone']}** ({A['wrong_alone']}) |\n"
          f"| Coding solved /72 | **{C['mixed']}** | **{C['alone']}** |\n"
          f"| Wall for both workloads | **{w['mixed'] / 60:.0f} min** | **{w['sequential'] / 60:.0f} min** ({w['arith_alone'] / 60:.0f} + {w['coding_alone'] / 60:.0f}) |\n"
          f"| GPU energy for both | **{e['mixed']} Wh** | **{e['sequential']} Wh** |\n"
          f"| Server tokens | {res['tokens']['mixed']:,.0f} | {res['tokens']['sequential']:,.0f} |\n\n"
          f"In M the arithmetic swarm finished after {w['mixed_arith_done'] / 60:.0f} min and the coding swarm after {w['mixed_coding_done'] / 60:.0f} min. "
          f"Paired: arithmetic M vs alone +{A['paired']['wins']} / -{A['paired']['losses']} (p = {A['paired']['p']:.2g}); coding +{C['paired']['wins']} / -{C['paired']['losses']} (p = {C['paired']['p']:.2g}).\n\n"
          'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
    verdict = ('**Serve the two swarms together.**' if res['decision']['recommend_mixed'] else
               '**Run them one after the other** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
    (OUT / 'REPORT.md').write_text(f"""# Arithmetic and coding swarms on the fleet at the same time (mixed-task-v1)

Plans [`MIXED_TASK_PLAN.json`](../../MIXED_TASK_PLAN.json) (with the four runner plans it names) were frozen and pushed before
the fresh corpus arithmetic-hard-v13 was generated and before any call with seeds 10-12 on coding-hard-v1. Both workloads
use today's defaults: arithmetic roll8strategy (96 cases), coding early stop + staggered start (72 cases). Inkling-2-Mini
x4, mem fraction 0.75. M ran both at once (10 + 10 client requests per node); Sa and Sc ran them alone (20 per node).

## Result

{md}
{verdict}

Why: the static split. Each workload got half of the per-node concurrency for the whole run, and when the coding swarm
finished (after {w['mixed_coding_done'] / 60:.0f} min) the arithmetic swarm kept running alone with only 10 requests per node for the last
{(w['mixed'] - w['mixed_coding_done']) / 60:.0f} min, so part of the fleet stood idle; the long hard-case tails of both swarms do not overlap enough to make up for it.
Accuracy is unaffected by sharing (both paired differences are run-to-run noise). Sharing would need a dynamic split
(one global request budget per node handed to whichever swarm has work), which this study did not test.

Files: `inkling/mixed_arms.py` (concurrent driver), `inkling/arms.py`, `inkling/coding_arms.py`, `inkling/report_mixed_task.py`,
numbers in [report.json](report.json).
""")
    print(md)


if __name__ == '__main__':
    main()
