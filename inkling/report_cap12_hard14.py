#!/usr/bin/env python3
"""Report for SWARM_CAP12_HARD14_PLAN.json (study swarm-cap12-hard14-v1): D roll8strategy (cap 8, default) vs D12
roll12strategy (cap 12, failure-driven) on arithmetic-hard-v14. Writes results/swarm-cap12-hard14-v1/{REPORT.md,
report.json, tables.md}."""
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

STUDY = 'swarm-cap12-hard14-v1'
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
        res['decision'] = dict(zero_wrong=bpp['wrong'] == 0, solved_at_least_d_plus_2=bpp['solved'] >= bp['solved'] + 2,
                               late_rescues_at_least_1=m['late_rescues'] >= 1)
        d = res['decision']
        a12, b12 = load(['swarm-cap12-hard12-v1-roll12strategy'])[0], load(['swarm-cap12-hard12-v1-roll8strategy'])[0]
        pa = {('v12',) + k: v for k, v in a12.items()} | {('v14',) + k: v for k, v in data['roll12strategy'][0].items()}
        pb = {('v12',) + k: v for k, v in b12.items()} | {('v14',) + k: v for k, v in data['roll8strategy'][0].items()}
        res['pooled_v12_v14'] = paired(pa, pb)
        res['pooled_solved'] = dict(cap12=sum(v['solved'] for v in pa.values()), cap8=sum(v['solved'] for v in pb.values()),
                                    wrong_cap12=sum(v['wrong'] for v in pa.values()))
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
        (OUT / 'REPORT.md').write_text(f"""# Replication: escalation cap 12 vs 8 on a fresh corpus (swarm-cap12-hard14-v1)

Plan [`SWARM_CAP12_HARD14_PLAN.json`](../../SWARM_CAP12_HARD14_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v14 (generator seed 2026112110) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **D roll8strategy** (default): 4 in flight; failures replaced by fresh-seed agents with strategy hints, up to 8.
- **D12 roll12strategy**: identical with up to 12 agents (strictly failure-driven, no time trigger).

## Result

{md}
{verdict}

Pre-registered pooled hard-v12 + hard-v14 (192 cases): cap 12 {res['pooled_solved']['cap12']} vs cap 8 {res['pooled_solved']['cap8']},
paired +{res['pooled_v12_v14']['wins']} / -{res['pooled_v12_v14']['losses']} (p = {res['pooled_v12_v14']['p']:.2g}), cap 12 wrong answers {res['pooled_solved']['wrong_cap12']}. Cost on hard-v14:
{res['arms']['roll12strategy']['energy_wh_per_solved']:.2f} vs {res['arms']['roll8strategy']['energy_wh_per_solved']:.2f} Wh per solved case (reported, not a gate: the owner's priority is quality).

Files: `run_variants.py` (`roll12strategy`), `inkling/arms.py`, `inkling/report_cap12_hard14.py`, numbers in [report.json](report.json).
""")
    print(md)
    return res


if __name__ == '__main__':
    main()
