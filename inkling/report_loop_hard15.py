#!/usr/bin/env python3
"""Report for swarm-loop-hard15-v1: default roll8strategy with xl_forced_original (D) vs with the loop watchdog
xl_forced_watchdog (L) on arithmetic-hard-v15. Writes results/swarm-loop-hard15-v1/{REPORT.md, report.json, tables.md}."""
import json
from pathlib import Path

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

OUT = ROOT / 'results' / 'swarm-loop-hard15-v1'
ARMS = [('D', 'swarm-loop-hard15-v1-d-roll12strategy'), ('L', 'swarm-loop-hard15-v1-l-roll12strategy')]


def loop_stats(run):
    stops = plans = accepted = 0
    for f in (RUNS / run / 'agents').glob('*.jsonl'):
        recs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        if any(r.get('type') == 'request_end' and r.get('loop_stop') for r in recs):
            stops += 1
            end = next((r for r in reversed(recs) if r.get('type') == 'puzzle_end'), {})
            plans += isinstance(end.get('plan'), dict)
            judge = RUNS / run / 'judges' / f.name
            if judge.exists():
                accepted += any(json.loads(l).get('type') == 'judge_end' and json.loads(l).get('verdict') is True
                                for l in judge.read_text().splitlines() if l.strip())
    return dict(loop_stops=stops, plans_at_stop=plans, accepted_at_stop=accepted)


def main():
    data = {k: load([d]) for k, d in ARMS if (RUNS / d / 'cases.jsonl').exists()}
    res = dict(arms={k: summarize(*v) for k, v in data.items()}, loops={k: loop_stats(d) for k, d in ARMS if k in data})
    if len(data) == 2:
        d, l = res['arms']['D'], res['arms']['L']
        res['paired'] = paired(data['L'][0], data['D'][0])
        res['ratios'] = dict(tokens=round(l['server_tokens_per_case'] / d['server_tokens_per_case'], 3), wall=round(l['arm_wall_seconds'] / d['arm_wall_seconds'], 3))
        res['decision'] = dict(zero_wrong=l['wrong'] == 0, solved_at_least_d_minus_2=l['solved'] >= d['solved'] - 2,
                               tokens_at_most_95pct=res['ratios']['tokens'] <= .95)
        res['decision']['adopt_watchdog'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(D='D: default (no watchdog)', L='L: default + loop watchdog')
    lines = ['| Arm | Solved | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Loop stops (plans, accepted) |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for k, _ in ARMS:
        if k in data:
            s, q = res['arms'][k], res['loops'][k]
            lines.append(f"| {names[k]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,} | {s['arm_wall_seconds'] / 60:.0f} min | "
                         f"{s['energy_wh']} | {s['energy_wh_per_solved']:.2f} | {q['loop_stops']} ({q['plans_at_stop']}, {q['accepted_at_stop']}) |")
    md = '\n'.join(lines) + '\n'
    if 'paired' in res:
        p = res['paired']
        md += (f"\nL vs D paired: +{p['wins']} / -{p['losses']} (p = {p['p']:.3g}); L/D tokens {res['ratios']['tokens']}, wall {res['ratios']['wall']}.\n\n"
               'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
        verdict = ('**The loop watchdog becomes part of the default.**' if res['decision']['adopt_watchdog'] else
                   '**The default stays without the watchdog** (' + ', '.join(k for k, v in res['decision'].items() if v is False) + ').')
        (OUT / 'REPORT.md').write_text(f"""# Loop watchdog (swarm-loop-hard15-v1)

Plans `SWARM_LOOP_HARD15_D_PLAN.json` and `SWARM_LOOP_HARD15_L_PLAN.json` were frozen and pushed before the fresh corpus
arithmetic-hard-v15 was generated. Fable round-2 idea 3. Both arms run the default policy roll12strategy; L uses the
worker variant `xl_forced_watchdog` (branch research/xl-watchdog-v1): a thinking stream whose last 2,000 characters
compress below a zlib ratio of 0.06 twice in a row (checked every 500 characters) is stopped and its answer forced, as
after a length cut; the failed agent is replaced as usual. Inkling-2-Mini x4, mem fraction 0.75, each arm alone.

## Result

{md}
{verdict}

Files: worker `forced72.py` on research/xl-watchdog-v1, `inkling/arms.py`, `inkling/report_loop_hard15.py`, numbers in [report.json](report.json).
""")
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
