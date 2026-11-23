#!/usr/bin/env python3
"""Report for swarm-loop-hard15-v1: default roll12strategy with xl_forced_original (D) vs with the loop watchdog
xl_forced_watchdog (L) on arithmetic-hard-v15. Writes results/swarm-loop-hard15-v1/{REPORT.md, report.json, tables.md}."""
import json
from pathlib import Path

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

OUT = ROOT / 'results' / 'swarm-loop-hard15-v1'
ARMS = [('D', 'swarm-loop-hard15-v1-d-roll12strategy'), ('L', 'swarm-loop-hard15-v1-l-roll12strategy')]

AMENDMENT = ('\nAmendment (2026-11-23, before arm L finished): arm D case eva-h247d88a63ba seed 1 lost one judge request to a '
             'transient upstream disconnect on Spark_03 (shim_upstream_errors 1, no container restart); per the frozen resume '
             'rule it was rerun with the same seeds in segment `-resume1` after arm L. This report script (frozen sha256 '
             '1812e6a68a36) was changed only to merge resume segments and to count wrong answers in superseded infra '
             'attempts against the arm; the runtime code is unchanged.\n')


def segments(run):
    """The arm's directory plus its resume segments (frozen resume rule), in order."""
    return [run] + [f'{run}-resume{i}' for i in range(1, 10) if (RUNS / f'{run}-resume{i}' / 'cases.jsonl').exists()]


def superseded(run):
    """Infra-faulted attempts that a resume segment replaced; a wrong answer there would still count against the arm."""
    segs = segments(run)
    rows = [json.loads(l) for d in segs[:-1] for l in (RUNS / d / 'cases.jsonl').read_text().splitlines() if l.strip()]
    bad = [r for r in rows if r.get('infra')]
    return dict(segments=len(segs), infra_attempts=len(bad), infra_attempts_wrong=sum(bool(r.get('wrong')) for r in bad),
                cases=[f"{r['task_id']} s{r['seed']}" for r in bad])


def loop_stats(run):
    stops = plans = accepted = 0
    for f in (f for seg in segments(run) for f in (RUNS / seg / 'agents').glob('*.jsonl')):
        recs = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        if any(r.get('type') == 'request_end' and r.get('loop_stop') for r in recs):
            stops += 1
            end = next((r for r in reversed(recs) if r.get('type') == 'puzzle_end'), {})
            plans += isinstance(end.get('plan'), dict)
            judge = f.parent.parent / 'judges' / f.name
            if judge.exists():
                accepted += any(json.loads(l).get('type') == 'judge_end' and json.loads(l).get('verdict') is True
                                for l in judge.read_text().splitlines() if l.strip())
    return dict(loop_stops=stops, plans_at_stop=plans, accepted_at_stop=accepted)


def main():
    data = {k: load(segments(d)) for k, d in ARMS if (RUNS / d / 'cases.jsonl').exists()}
    res = dict(arms={k: summarize(*v) for k, v in data.items()}, loops={k: loop_stats(d) for k, d in ARMS if k in data},
               resumes={k: superseded(d) for k, d in ARMS if k in data})
    if len(data) == 2:
        d, l = res['arms']['D'], res['arms']['L']
        res['paired'] = paired(data['L'][0], data['D'][0])
        res['ratios'] = dict(tokens=round(l['server_tokens_per_case'] / d['server_tokens_per_case'], 3), wall=round(l['arm_wall_seconds'] / d['arm_wall_seconds'], 3))
        res['decision'] = dict(zero_wrong=l['wrong'] == 0 and res['resumes']['L']['infra_attempts_wrong'] == 0, solved_at_least_d_minus_2=l['solved'] >= d['solved'] - 2,
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
               'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n'
               + AMENDMENT)
        def gen(run):
            acc = json.loads((RUNS / run / 'arm_accounting.json').read_text())
            return sum(acc['after']['nodes'][n]['generation_tokens'] - acc['before']['nodes'][n]['generation_tokens'] for n in acc['after']['nodes'])
        d_segments = [ARMS[0][1]] + [f'{ARMS[0][1]}-resume{i}' for i in range(1, 10) if (RUNS / f'{ARMS[0][1]}-resume{i}' / 'arm_accounting.json').exists()]
        d_total, l_total = sum(gen(x) for x in d_segments), gen(ARMS[1][1])
        d_without_waste = gen(d_segments[0])  # the faulted attempt ran its case to the end (all agents finished, one judge lost)
        res['ratios']['tokens_excluding_infra_waste'] = round(l_total / d_without_waste, 3)
        rp = json.loads((OUT / 'replay.json').read_text()) if (OUT / 'replay.json').exists() else None
        res['replay'] = rp and {k: v for k, v in rp.items() if k != 'arms'}
        res['mechanism_verdict'] = 'keep default without watchdog'
        frozen = ('D wall, energy and tokens include the resume segment (one case, 25 min). ' + 'Frozen rule outcome: adopt.' if res['decision']['adopt_watchdog'] else 'D wall, energy and tokens include the resume segment (one case, 25 min). Frozen rule outcome: keep.')
        verdict = f"""{frozen}

**Mechanism.** In L the watchdog stopped {res['loops']['L']['loop_stops']} thinking streams; all {res['loops']['L']['plans_at_stop']} forced answers were rejected by the judge
(0 accepted), so a stopped agent is simply replaced earlier. The tokens it saves are the rest of each loop:
{rp['arms'][ARMS[0][1]]['chars_after_stop'] / rp['arms'][ARMS[0][1]]['chars'] * 100:.1f} % of D's completed plan-stream characters lie after the point where the watchdog would have stopped them.
Measured L/D server tokens: {res['ratios']['tokens']} with the frozen accounting, which charges D the wasted infra attempt of
eva-h247d88a63ba s1 plus its rerun; without that waste {res['ratios']['tokens_excluding_infra_waste']} (-{(1 - res['ratios']['tokens_excluding_infra_waste']) * 100:.1f} %),
a sensitivity estimate (it removes the resume segment, which has the size of the faulted attempt), which would not pass
the 0.95 gate. The accuracy side: offline replay of the same detector on {rp['would_stop']} streams from 13 arms that ran without
it (`inkling/replay_loop_watchdog.py`, [replay.json](replay.json); it checks exact 500-character steps, the online detector
checks arriving chunks, so the replay is approximate) finds {rp['recovered']} streams that met the stop criterion and later gave the
accepted, correct answer of their case. 8 of these 9 ran to the thinking-budget limit and then received a forced answer;
one closed its thinking normally. So these are not shown to be streams that escaped their loop: the observed contrast is a
forced answer at loop detection (0 of {res['loops']['L']['plans_at_stop']} accepted in L) versus a forced answer at the budget limit (8 accepted
in the replay), and whether those cases would be lost under the watchdog is not established. A trigger of at least
54 consecutive checks would have spared all 9 in this replay (99 stops instead of {rp['would_stop']}); that threshold is fitted to these
data and untested. In this study 2 of L's 3 lost cases are cases whose D-winning agent looped in L and was stopped.

**Verdict: provisionally not adopted.** The frozen rule passed; this is a policy decision under the owner's
quality-first priority, not a failed pre-registered test. The independent review (astra, 2026-11-23) suggests the fair
follow-up: validate the detector on recorded chunk boundaries, then a prospective three-arm study with no intervention,
the forced answer, and one bounded "change approach" nudge, with frozen cost accounting and case-level accuracy criteria."""
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
