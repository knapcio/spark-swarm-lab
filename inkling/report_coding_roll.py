#!/usr/bin/env python3
"""Report for coding-roll-v1: S (early stop + stagger, default) vs R4 / R2 (failure-driven replacement with 4 / 2 agents
in flight) on coding-hard-v1, fresh seeds 13-15. Writes results/coding-roll-v1/{REPORT.md, report.json, tables.md}."""
import json
import statistics

from report_coding_earlystop import RUNS, ROOT, accounting, stop_arm
from report_hard4 import sign_test

OUT = ROOT / 'results' / 'coding-roll-v1'
ARMS = [('S', 'coding-roll-v1-s'), ('R4', 'coding-roll-v1-r4'), ('R2', 'coding-roll-v1-r2')]


def arm(name):
    cases, acct = stop_arm(name), accounting(name)
    stops = sorted(c['stop_seconds'] for c in cases.values() if c['stop_seconds'] is not None)
    return cases, dict(solved=sum(c['solved'] for c in cases.values()), answered=sum(c['answered'] for c in cases.values()),
                       wrong=sum(c['answered'] and not c['solved'] for c in cases.values()),
                       tokens_per_case=round(acct['server_tokens'] / len(cases)), wall=acct['wall'], wh=acct['wh'],
                       started_per_case=round(sum(c['started'] for c in cases.values()) / len(cases), 2),
                       never_started=sum(c['never_started'] for c in cases.values()),
                       stop_median=round(statistics.median(stops)) if stops else None, stop_p90=round(stops[int(.9 * len(stops))]) if stops else None)


def main():
    data = {k: arm(d) for k, d in ARMS if (RUNS / d / 'cases.json').exists()}
    res = dict(arms={k: v[1] for k, v in data.items()}, paired={})
    S = data['S']
    for k in ('R4', 'R2'):
        if k in data:
            c = data[k][0]
            w = sum(c[x]['solved'] and not S[0][x]['solved'] for x in c)
            l = sum(S[0][x]['solved'] and not c[x]['solved'] for x in c)
            res['paired'][k] = dict(wins=w, losses=l, p=sign_test(w, l))
            res['arms'][k]['tokens_ratio'] = round(data[k][1]['tokens_per_case'] / S[1]['tokens_per_case'], 3)
    if all(k in data for k in ('R4', 'R2')):
        s, r4, r2 = S[1], data['R4'][1], data['R2'][1]
        adopt = 'R2' if (r2['solved'] >= s['solved'] - 2 and r2['tokens_ratio'] <= .70) else \
                'R4' if (r4['solved'] >= s['solved'] - 2 and r4['tokens_ratio'] <= .85) else 'S'
        res['decision'] = dict(adopt=adopt)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    names = dict(S='S: early stop + stagger 4+4 at 300 s (default)', R4='R4: replace failures, 4 in flight', R2='R2: replace failures, 2 in flight')
    lines = ['| Arm | Solved /72 | Wrong | Server tokens/case | Arm wall | GPU Wh | Wh per solved | Stop median / p90 | Agents started per case |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for k, _ in ARMS:
        if k in data:
            a = res['arms'][k]
            ratio = f" ({(a['tokens_ratio'] - 1) * 100:+.0f} %)" if 'tokens_ratio' in a else ''
            lines.append(f"| {names[k]} | **{a['solved']}** | {a['wrong']} | {a['tokens_per_case']:,}{ratio} | {a['wall'] / 60:.0f} min | {a['wh']} | "
                         f"{a['wh'] / max(1, a['solved']):.2f} | {a['stop_median']} / {a['stop_p90']} s | {a['started_per_case']} |")
    md = '\n'.join(lines) + '\n\n' + ''.join(f"{k} vs S paired: +{v['wins']} / -{v['losses']} (p = {v['p']:.2g}). " for k, v in res['paired'].items()) + '\n'
    if 'decision' in res:
        md += f"\nFrozen decision rule (R2 if solved >= S - 2 and tokens <= 0.70 x S; else R4 if solved >= S - 2 and tokens <= 0.85 x S; else S): adopt **{res['decision']['adopt']}**.\n"
        (OUT / 'REPORT.md').write_text(f"""# Coding swarm: replace failed agents instead of a timed second wave (coding-roll-v1)

Plans `CODING_ROLL_S_PLAN.json`, `CODING_ROLL_R4_PLAN.json` and `CODING_ROLL_R2_PLAN.json` were frozen and pushed before any
call with seeds 13-15 on coding-hard-v1 (24 evaluation tasks x 3 fresh seeds = 72 cases, agent seed offset 4700).
Idea 1 of Fable's round-2 list (IDEAS-swarm-round2-fable.md). All arms use early stop at the first proposal that passes
the public tests; each ran alone on the fleet (Inkling-2-Mini x4, mem fraction 0.75, 20 agents per node).

## Result

{md}
Files: `run_coding_earlystop.py` (`rolling`), `inkling/coding_arms.py`, `inkling/report_coding_roll.py`, numbers in [report.json](report.json).
""")
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
