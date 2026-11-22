#!/usr/bin/env python3
"""Report for SWARM_WIDTH3_HARD11_PLAN.json (swarm-width3-hard11-v1): B+ roll8cancel (4 in flight) vs B+3 roll3to8
(3 in flight) on arithmetic-hard-v11. Writes results/swarm-width3-hard11-v1/{REPORT.md, report.json, tables.md}."""
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

STUDY = 'swarm-width3-hard11-v1'
OUT = ROOT / 'results' / STUDY
ARMS = [('B+', 'roll8cancel'), ('B+3', 'roll3to8')]


def main():
    data = {pol: load([f'{STUDY}-{pol}']) for _, pol in ARMS if (RUNS / f'{STUDY}-{pol}' / 'cases.jsonl').exists()}
    res = dict(study=STUDY, arms={pol: summarize(*data[pol]) for pol in data})
    for pol in data:
        cases = data[pol][0]
        res['arms'][pol]['agents_per_case'] = round(sum(sum(a.get('started', True) for a in r['agents']) for r in cases.values()) / len(cases), 2)
        res['arms'][pol]['escalated_cases'] = sum(r.get('escalated_agents', 0) > 0 for r in cases.values())
    if len(data) == 2:
        b, w = res['arms']['roll8cancel'], res['arms']['roll3to8']
        res['paired'] = paired(data['roll3to8'][0], data['roll8cancel'][0])
        res['ratios'] = dict(tokens=round(w['server_tokens_per_case'] / b['server_tokens_per_case'], 3),
                             wall=round(w['arm_wall_seconds'] / b['arm_wall_seconds'], 3),
                             energy=round(w['energy_wh'] / b['energy_wh'], 3))
        res['decision'] = dict(zero_wrong=w['wrong'] == 0, tokens_at_most_90pct=res['ratios']['tokens'] <= .90,
                               solved_at_least_bplus_minus_2=w['solved'] >= b['solved'] - 2, wall_at_most_110pct=res['ratios']['wall'] <= 1.10)
        res['decision']['adopt_roll3to8'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(roll8cancel='B+ roll8cancel (4 in flight, default)', roll3to8='B+3 roll3to8 (3 in flight)')
    lines = ['| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | Case wall median / p90 | GPU Wh | Wh per solved | Agents per case | Escalated cases |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for _, pol in ARMS:
        if pol in data:
            s = res['arms'][pol]
            lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,} | {s['arm_wall_seconds'] / 60:.0f} min | "
                         f"{s['case_seconds']['median']} / {s['case_seconds']['p90']} s | {s['energy_wh']} | {s['energy_wh_per_solved']:.2f} | {s['agents_per_case']} | {s['escalated_cases']} |")
    md = '\n'.join(lines) + '\n'
    if 'paired' in res:
        p = res['paired']
        md += (f"\nB+3 vs B+ paired: +{p['wins']} / -{p['losses']} (p = {p['p']:.3g}); B+3/B+ tokens {res['ratios']['tokens']}, wall {res['ratios']['wall']}, "
               f"energy {res['ratios']['energy']}.\n\nFrozen decision rule: " + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
        verdict = ('**B+3 (3 agents in flight) becomes the default.**' if res['decision']['adopt_roll3to8'] else
                   '**B+ (4 in flight) stays the default** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
        (OUT / 'REPORT.md').write_text(f"""# Three agents in flight instead of four (swarm-width3-hard11-v1)

Plan [`SWARM_WIDTH3_HARD11_PLAN.json`](../../SWARM_WIDTH3_HARD11_PLAN.json) was frozen and pushed before the fresh corpus
arithmetic-hard-v11 (generator seed 2026112107) was generated. Inkling-2-Mini on Spark_01..04 (mem fraction 0.75),
96 paired cases per arm, each arm alone on the fleet, server-side token counting, GPU-rail energy.

- **B+ roll8cancel** (default): 4 agents in flight; every agent ending without an accepted plan is replaced by a fresh-seed
  agent, up to 8; the first accepted plan cancels the rest.
- **B+3 roll3to8**: identical with 3 agents in flight.

## Result

{md}
{verdict}

Files: `run_variants.py` (`roll3to8`), `inkling/arms.py`, `inkling/report_width3_hard11.py`, numbers in [report.json](report.json).
""")
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
