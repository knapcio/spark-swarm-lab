#!/usr/bin/env python3
"""Report for coding-earlystop-v1: E (early stop at the first feedback-passing proposal in time, run_coding_earlystop.py)
vs F (8 agents to the end, slot-order first feedback-passing, run_coding_agents.py) on coding-hard-v1, seeds 4-6.
Writes results/coding-earlystop-v1/{report.json, tables.md}."""
import json
import statistics
from datetime import datetime
from pathlib import Path

from report_hard4 import sign_test

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'runs'
OUT = ROOT / 'results' / 'coding-earlystop-v1'


def finished_at(events):
    last = None
    for line in Path(events).read_text().splitlines():
        try:
            last = json.loads(line).get('timestamp') or last
        except ValueError:
            pass
    return datetime.fromisoformat(last).timestamp() if last else None


def full_arm(name):
    rows = json.loads((RUNS / name / 'summary.json').read_text())
    cases = {}
    for r in rows:
        cases.setdefault((r['task_id'], r['seed']), {})[r['agent']] = dict(
            feedback=bool(r['feedback_pass']), holdout=bool(r['holdout_pass']), tokens=r['completion_tokens'] or 0,
            end=finished_at(r['events']))
    out = {}
    for k, c in cases.items():
        slot = next((a for a in sorted(c) if c[a]['feedback']), None)
        timed = min((a for a in c if c[a]['feedback']), key=lambda a: c[a]['end'], default=None)
        out[k] = dict(slot_pick=slot, time_pick=timed, solved=bool(slot is not None and c[slot]['holdout']),
                      solved_time_rule=bool(timed is not None and c[timed]['holdout']),
                      oracle=any(a['holdout'] and a['feedback'] for a in c.values()), one=bool(c.get(0, {}).get('holdout')),
                      agents=len(c), tokens=sum(a['tokens'] for a in c.values()))
    return out


def stop_arm(name):
    return {(c['task_id'], c['seed']): c for c in json.loads((RUNS / name / 'cases.json').read_text())}


def accounting(name):
    a = json.loads((RUNS / name / 'arm_accounting.json').read_text())
    return dict(server_tokens=a['server']['total']['generation_tokens'], wall=a['runner_wall_seconds'],
                wh=(a['energy'] or {}).get('total_wh'), client_cancels=a['server']['total']['shim_client_cancels'],
                upstream_errors=a['server']['total']['shim_upstream_errors'], exit=a['runner_exit'])


def main():
    F, E = full_arm('coding-earlystop-v1-full'), stop_arm('coding-earlystop-v1-stop')
    keys = sorted(F)
    assert set(keys) == set(E), (len(keys), len(E))
    aF, aE = accounting('coding-earlystop-v1-full'), accounting('coding-earlystop-v1-stop')
    n = len(keys)
    sF, sE = sum(F[k]['solved'] for k in keys), sum(E[k]['solved'] for k in keys)
    w = sum(E[k]['solved'] and not F[k]['solved'] for k in keys)
    l = sum(F[k]['solved'] and not E[k]['solved'] for k in keys)
    sel = sum(F[k]['solved_time_rule'] for k in keys) - sF
    stops = [E[k]['stop_seconds'] for k in keys if E[k]['stop_seconds'] is not None]
    res = dict(cases=n, full=dict(solved=sF, solved_time_rule=sF + sel, oracle=sum(F[k]['oracle'] for k in keys),
                                  one=sum(F[k]['one'] for k in keys), answered=sum(F[k]['slot_pick'] is not None for k in keys), **aF,
                                  tokens_per_case=round(aF['server_tokens'] / n)),
               stop=dict(solved=sE, answered=sum(E[k]['answered'] for k in keys), cancelled=sum(E[k]['cancelled'] for k in keys),
                         never_started=sum(E[k]['never_started'] for k in keys), **aE,
                         tokens_per_case=round(aE['server_tokens'] / n),
                         stop_seconds=dict(median=round(statistics.median(stops)), max=round(max(stops))) if stops else None),
               paired_stop_vs_full=dict(wins=w, losses=l, p=sign_test(w, l)), selection_effect_inside_full=sel)
    res['ratios'] = dict(tokens=round(aE['server_tokens'] / aF['server_tokens'], 3), wall=round(aE['wall'] / aF['wall'], 3),
                         energy=round(aE['wh'] / aF['wh'], 3) if aE['wh'] and aF['wh'] else None)
    res['decision'] = dict(selection_effect_at_least_minus_1=sel >= -1, tokens_at_most_80pct=res['ratios']['tokens'] <= .80,
                           wall_lower=res['ratios']['wall'] < 1)
    res['decision']['adopt_early_stop'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    f, e = res['full'], res['stop']
    md = (f"| Arm | Solved /{n} | Server tokens/case | Arm wall | GPU energy | Wh per solved | Cancelled / never started agents |\n"
          f"|---|---:|---:|---:|---:|---:|---:|\n"
          f"| F: 8 agents to the end (slot-order first passing) | **{f['solved']}** | {f['tokens_per_case']:,} | {f['wall'] / 60:.0f} min | "
          f"{f['wh']} Wh | {f['wh'] / max(1, f['solved']):.2f} | 0 / 0 |\n"
          f"| E: stop at first passing in time | **{e['solved']}** | {e['tokens_per_case']:,} ({(res['ratios']['tokens'] - 1) * 100:+.0f} %) | "
          f"{e['wall'] / 60:.0f} min ({(res['ratios']['wall'] - 1) * 100:+.0f} %) | {e['wh']} Wh | {e['wh'] / max(1, e['solved']):.2f} | "
          f"{e['cancelled']} / {e['never_started']} |\n\n"
          f"E vs F paired: +{w} / -{l} (p = {res['paired_stop_vs_full']['p']:.2g}). Inside F (same proposals, no generation noise): "
          f"time-order pick {f['solved_time_rule']} vs slot-order pick {f['solved']} (selection effect {sel:+d}). F oracle {f['oracle']}, "
          f"One Inkling (agent 0) {f['one']}.\n\nFrozen decision rule: " + ', '.join(f'{k} = {v}' for k, v in res['decision'].items()) + '\n')
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
