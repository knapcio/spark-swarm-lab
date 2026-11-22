#!/usr/bin/env python3
"""Report for SWARM_ALLHINTS_HARD15_PLAN.json (swarm-allhints-hard15-v1): D roll8strategy (default) vs H roll8allhints
(first four agents with distinct strategy hints) on arithmetic-hard-v14. Writes results/swarm-allhints-hard15-v1/."""
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

STUDY = 'swarm-allhints-hard15-v1'
OUT = ROOT / 'results' / STUDY
ARMS = [('D', 'roll8strategy'), ('H', 'roll8allhints')]


def first_wave(cases):
    return sum(r.get('selected_slot') is not None and r['selected_slot'] < 4 for r in cases.values())


def per_slot(cases):
    out = {}
    for s in range(4):
        sel = sum(r.get('selected_slot') == s for r in cases.values())
        out[s] = sel
    return out


def main():
    data = {pol: load([f'{STUDY}-{pol}']) for _, pol in ARMS if (RUNS / f'{STUDY}-{pol}' / 'cases.jsonl').exists()}
    res = dict(study=STUDY, arms={pol: summarize(*data[pol]) for pol in data})
    for pol in data:
        res['arms'][pol]['first_wave_answered'] = first_wave(data[pol][0])
        res['arms'][pol]['answered_by_slot_0_3'] = per_slot(data[pol][0])
    if len(data) == 2:
        d, h = res['arms']['roll8strategy'], res['arms']['roll8allhints']
        res['paired'] = paired(data['roll8allhints'][0], data['roll8strategy'][0])
        res['decision'] = dict(zero_wrong=h['wrong'] == 0, solved_at_least_d_plus_2=h['solved'] >= d['solved'] + 2,
                               first_wave_not_lower=h['first_wave_answered'] >= d['first_wave_answered'],
                               tokens_at_most_105pct=h['server_tokens_per_case'] <= 1.05 * d['server_tokens_per_case'])
        res['decision']['adopt_roll8allhints'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(roll8strategy='D roll8strategy (default)', roll8allhints='H roll8allhints (hints for every agent)')
    lines = ['| Arm | Solved | Wrong | Abstain | Answered by first four | Server tokens/case | Arm wall | GPU Wh | Wh per solved |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for _, pol in ARMS:
        if pol in data:
            s = res['arms'][pol]
            lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['first_wave_answered']} | {s['server_tokens_per_case']:,} | "
                         f"{s['arm_wall_seconds'] / 60:.0f} min | {s['energy_wh']} | {s['energy_wh_per_solved']:.2f} |")
    md = '\n'.join(lines) + '\n'
    if 'paired' in res:
        p = res['paired']
        md += (f"\nH vs D paired: +{p['wins']} / -{p['losses']} (p = {p['p']:.3g}). Answers by first-wave slot (0-3), H: "
               f"{res['arms']['roll8allhints']['answered_by_slot_0_3']}, D: {res['arms']['roll8strategy']['answered_by_slot_0_3']}.\n\nFrozen decision rule: "
               + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
        verdict = ('**roll8allhints becomes the default.**' if res['decision']['adopt_roll8allhints'] else
                   '**roll8strategy stays the default** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
        (OUT / 'REPORT.md').write_text(f"""# Strategy hints for the first wave too (swarm-allhints-hard15-v1)

Plan [`SWARM_ALLHINTS_HARD15_PLAN.json`](../../SWARM_ALLHINTS_HARD15_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v15 (generator seed 2026112111) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **D roll8strategy** (default): the first four agents get the plain task; escalation agents get distinct strategy hints.
- **H roll8allhints**: agent k gets strategy hint k mod 4 from the start (work backward / product close to the target /
  use every number / one large intermediate first).

## Result

{md}
{verdict}

Files: `run_variants.py` (`roll8allhints`), `inkling/arms.py`, `inkling/report_allhints_hard15.py`, numbers in [report.json](report.json).
""")
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
