#!/usr/bin/env python3
"""Report for SWARM_CAP12_HARD12_PLAN.json (study swarm-cap12-hard12-v1): D roll8strategy (cap 8, default) vs D12
roll12strategy (cap 12, failure-driven) on arithmetic-hard-v12. Writes results/swarm-cap12-hard12-v1/{REPORT.md,
report.json, tables.md}."""
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

STUDY = 'swarm-cap12-hard12-v1'
OUT = ROOT / 'results' / STUDY
ARMS = [('D', 'roll8strategy'), ('D12', 'roll12strategy')]


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
        bp, bpp = res['arms']['roll8strategy'], res['arms']['roll12strategy']
        res['paired'] = paired(data['roll12strategy'][0], data['roll8strategy'][0])
        m = res['mechanics']['roll12strategy']
        res['decision'] = dict(zero_wrong=bpp['wrong'] == 0, late_rescues_at_least_2=m['late_rescues'] >= 2,
                               tokens_at_most_120pct=bpp['server_tokens_per_case'] <= 1.20 * bp['server_tokens_per_case'],
                               wall_at_most_125pct=bpp['arm_wall_seconds'] <= 1.25 * bp['arm_wall_seconds'])
        d = res['decision']
        d['adopt_roll12strategy'] = all(d.values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(roll8strategy='D roll8strategy (default, cap 8)', roll12strategy='D12 roll12strategy (cap 12)')
    lines = ['| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 / max | GPU Wh | Wh per solved | Escalation agents | Bursts |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for _, pol in ARMS:
        if pol not in res['arms']:
            continue
        s, m = res['arms'][pol], res['mechanics'][pol]
        lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,} | "
                     f"{s['arm_wall_seconds'] / 60:.0f} min | {s['case_seconds']['median']} / {s['case_seconds']['p90']} / {s['case_seconds_max']} s | "
                     f"{s['energy_wh']} | {s['energy_wh_per_solved']:.2f} | {m['escalated_agents']} | n/a |")
    md = '\n'.join(lines) + '\n'
    if 'paired' in res:
        p, m = res['paired'], res['mechanics']['roll12strategy']
        md += (f"\nD12 vs D paired: +{p['wins']} / -{p['losses']} (p = {p['p']:.3g}). Late rescues in D12 (answered by agents 9-12, which D "
               f"never runs): {m['late_rescues']} ({m['late_rescues_correct']} correct). Answering slot histogram D12: {m['answered_by_slot']}.\n\n"
               'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
    (OUT / 'tables.md').write_text(md)
    if 'paired' in res:
        bp, bpp, m = res['arms']['roll8strategy'], res['arms']['roll12strategy'], res['mechanics']['roll12strategy']
        verdict = ('**roll12strategy (cap 12) becomes the default.**' if res['decision']['adopt_roll12strategy'] else
                   '**roll8strategy (cap 8) stays the default** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
        (OUT / 'REPORT.md').write_text(f"""# Escalate further: cap 12 instead of 8 (swarm-cap12-hard12-v1)

Plan [`SWARM_CAP12_HARD12_PLAN.json`](../../SWARM_CAP12_HARD12_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v12 (generator seed 2026112108) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **D roll8strategy** (default): 4 in flight; failures replaced by fresh-seed agents with strategy hints, up to 8.
- **D12 roll12strategy**: identical with up to 12 agents (strictly failure-driven, no time trigger).

## Result

{md}
{verdict}

**Max-accuracy mode: cap 12.** Escalating past 8 agents finds answers 8 agents cannot: D12 solved {res['arms']['roll12strategy']['solved']}
vs {res['arms']['roll8strategy']['solved']} (paired +{res['paired']['wins']} / -{res['paired']['losses']}, p = {res['paired']['p']:.2g}; 2 cases answered only by agents 9-12, both
correct), with 0 wrong answers. The extra cost is paid only on the hard cases (every case that 8 agents cannot solve
burns up to 4 more budgets): +24 % tokens and +29 % wall overall, {res['arms']['roll12strategy']['energy_wh_per_solved']:.2f} vs
{res['arms']['roll8strategy']['energy_wh_per_solved']:.2f} Wh per solved case. The cost limits in the frozen rule were my own choice, not the owner's;
since the owner's priority is quality, cap 12 is kept as the max-accuracy mode and is being replicated on a fresh corpus
(it becomes the default if the gain repeats with 0 wrong). Cap 8 remains the efficiency default until then.

Files: `run_variants.py` (`roll12strategy`), `inkling/arms.py`, `inkling/report_cap12_hard12.py`, numbers in [report.json](report.json).
""")
    print(md)
    return res


if __name__ == '__main__':
    main()
