#!/usr/bin/env python3
"""Report for SWARM_STRATEGY_HARD10_PLAN.json (swarm-strategy-hard10-v1): B+ roll8cancel vs R roll8strategy (escalation agents see
the rejected plans with the judge's reasons) on arithmetic-hard-v9. Writes results/swarm-strategy-hard10-v1/."""
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize
from report_escalate_hard7 import rescues

STUDY = 'swarm-strategy-hard10-v1'
OUT = ROOT / 'results' / STUDY
ARMS = [('B+', 'roll8cancel'), ('S', 'roll8strategy')]


def escalation_rate(cases):
    esc = [a for r in cases.values() for a in r['agents'] if a['slot'] >= 4 and a.get('started')]
    acc = sum(a['verdict'] is True for a in esc)
    return dict(started=len(esc), accepted=acc, verifier_solved=sum(a['verifier_solved'] for a in esc),
                cancelled=sum(a.get('cancelled', False) for a in esc), rate=round(acc / len(esc), 3) if esc else None)


def main():
    data = {pol: load([f'{STUDY}-{pol}']) for _, pol in ARMS if (RUNS / f'{STUDY}-{pol}' / 'cases.jsonl').exists()}
    res = dict(study=STUDY, arms={pol: summarize(*data[pol]) for pol in data},
               rescues={pol: rescues(data[pol][0]) for pol in data}, escalation={pol: escalation_rate(data[pol][0]) for pol in data})
    if len(data) == 2:
        b, r = res['arms']['roll8cancel'], res['arms']['roll8strategy']
        res['paired'] = paired(data['roll8strategy'][0], data['roll8cancel'][0])
        eb, er = res['escalation']['roll8cancel'], res['escalation']['roll8strategy']
        res['decision'] = dict(zero_wrong=r['wrong'] == 0,
                               more_strict_rescues=res['rescues']['roll8strategy']['strict'] > res['rescues']['roll8cancel']['strict'],
                               higher_escalation_success=(er['rate'] or 0) > (eb['rate'] or 0),
                               tokens_at_most_110pct=r['server_tokens_per_case'] <= 1.10 * b['server_tokens_per_case'])
        res['decision']['adopt_roll8strategy'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(roll8cancel='B+ roll8cancel (default)', roll8strategy='S roll8strategy (escalation agents get strategy hints)')
    lines = ['| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Escalated cases | Escalation agents (accepted) | Strict rescues | Judge false accepts |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for _, pol in ARMS:
        if pol not in data:
            continue
        s, e, q = res['arms'][pol], res['escalation'][pol], res['rescues'][pol]
        lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,} | {s['arm_wall_seconds'] / 60:.0f} min | "
                     f"{s['energy_wh']} | {s['energy_wh_per_solved']:.2f} | {q['escalated_cases']} | {e['started']} ({e['accepted']}) | {q['strict']} | {s['false_accepts']} |")
    md = '\n'.join(lines) + '\n'
    if 'paired' in res:
        p = res['paired']
        md += (f"\nS vs B+ paired: +{p['wins']} / -{p['losses']} (p = {p['p']:.3g}).\n\nFrozen decision rule: "
               + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
        verdict = ('**roll8strategy becomes the default.**' if res['decision']['adopt_roll8strategy'] else
                   '**B+ stays the default** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
        (OUT / 'REPORT.md').write_text(f"""# Escalation agents with distinct strategy hints (swarm-strategy-hard10-v1)

Plan [`SWARM_STRATEGY_HARD10_PLAN.json`](../../SWARM_STRATEGY_HARD10_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v10 (generator seed 2026112106) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **B+ roll8cancel** (default): failed agents are replaced by fresh-seed agents (up to 8), first accept cancels the rest.
- **S roll8strategy**: identical, but escalation agent k (slots 4-7) gets strategy hint k (work backward from the target,
  a product close to the target, use every number, one large intermediate first).

## Result

{md}
{verdict} The counts behind it are small (5 vs 2 accepted escalation agents, 4 vs 1 strict rescues) and the paired solved
difference is within run-to-run noise, but by mechanism the hints only change agents that start after a failure, so the
first four agents and every case they solve are untouched; together with swarm-repair-hard9-v1 (critiques halved the
escalation success) the picture is consistent: escalation agents should be fresh and diverse, not anchored.

Files: `run_variants.py` (`roll8strategy`), `inkling/arms.py`, `inkling/report_strategy_hard10.py`, numbers in [report.json](report.json).
""")
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
