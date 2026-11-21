#!/usr/bin/env python3
"""Report for SWARM_BURST_HARD8_PLAN.json (study swarm-burst-hard8-v1): B+ roll8cancel vs B++ roll12burst (cap 12 and a
900 s time trigger to 8 agents in flight) on arithmetic-hard-v8. Writes results/swarm-burst-hard8-v1/{REPORT.md,
report.json, tables.md}."""
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

STUDY = 'swarm-burst-hard8-v1'
OUT = ROOT / 'results' / STUDY
ARMS = [('B+', 'roll8cancel'), ('B++', 'roll12burst')]


def mechanics(cases):
    late = [k for k, r in cases.items() if r.get('selected_slot') is not None and r['selected_slot'] >= 8]
    bursts = [k for k, r in cases.items() if r.get('burst')]
    false_trigger = [k for k in bursts if cases[k].get('selected_slot') is not None and cases[k]['selected_slot'] < 4]
    return dict(late_rescues=len(late), late_rescues_correct=sum(cases[k]['solved'] for k in late), bursts=len(bursts),
                false_triggers=len(false_trigger), escalated_agents=sum(r.get('escalated_agents', 0) for r in cases.values()),
                answered_by_slot={s: sum(r.get('selected_slot') == s for r in cases.values()) for s in range(12)})


def main():
    data = {pol: load([f'{STUDY}-{pol}']) for _, pol in ARMS if (RUNS / f'{STUDY}-{pol}' / 'cases.jsonl').exists()}
    res = dict(study=STUDY, arms={pol: summarize(*data[pol]) for pol in data}, mechanics={pol: mechanics(data[pol][0]) for pol in data})
    for pol in data:
        res['arms'][pol]['case_seconds_max'] = round(max(r['case_seconds'] for r in data[pol][0].values()))
    if len(data) == 2:
        bp, bpp = res['arms']['roll8cancel'], res['arms']['roll12burst']
        res['paired'] = paired(data['roll12burst'][0], data['roll8cancel'][0])
        m = res['mechanics']['roll12burst']
        res['decision'] = dict(zero_wrong=bpp['wrong'] == 0,
                               tokens_at_most_115pct=bpp['server_tokens_per_case'] <= 1.15 * bp['server_tokens_per_case'],
                               late_rescues_at_least_2=m['late_rescues'] >= 2,
                               wall_at_most_90pct=bpp['arm_wall_seconds'] <= 0.90 * bp['arm_wall_seconds'])
        d = res['decision']
        d['adopt_roll12burst'] = d['zero_wrong'] and d['tokens_at_most_115pct'] and (d['late_rescues_at_least_2'] or d['wall_at_most_90pct'])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(roll8cancel='B+ roll8cancel (default)', roll12burst='B++ roll12burst (cap 12, burst at 900 s)')
    lines = ['| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts (false) |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for _, pol in ARMS:
        if pol not in res['arms']:
            continue
        s, m = res['arms'][pol], res['mechanics'][pol]
        lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,} | "
                     f"{s['arm_wall_seconds'] / 60:.0f} min | {s['case_seconds']['median']} / {s['case_seconds']['p90']} / {s['case_seconds_max']} s | "
                     f"{s['energy_wh']} | {s['energy_wh_per_solved']:.2f} | {m['escalated_agents']} | {m['bursts']} ({m['false_triggers']}) |")
    md = '\n'.join(lines) + '\n'
    if 'paired' in res:
        p, m = res['paired'], res['mechanics']['roll12burst']
        md += (f"\nB++ vs B+ paired: +{p['wins']} / -{p['losses']} (p = {p['p']:.3g}). Late rescues in B++ (answered by agents 9-12, which B+ "
               f"never runs): {m['late_rescues']} ({m['late_rescues_correct']} correct). Answering slot histogram B++: {m['answered_by_slot']}.\n\n"
               'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
    (OUT / 'tables.md').write_text(md)
    print(md)
    return res


if __name__ == '__main__':
    main()
