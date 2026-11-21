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
    verdict = ('**Early stop becomes the default for the Inkling coding swarm.**' if res['decision']['adopt_early_stop'] else
               '**The coding swarm keeps running all agents to the end**: ' + ', '.join(k for k, v in res['decision'].items() if v is False) + '.')
    (OUT / 'REPORT.md').write_text(f"""# Coding swarm: stop at the first proposal that passes the public tests (coding-earlystop-v1)

Plans [`CODING_EARLYSTOP_STOP_PLAN.json`](../../CODING_EARLYSTOP_STOP_PLAN.json) and
[`CODING_EARLYSTOP_FULL_PLAN.json`](../../CODING_EARLYSTOP_FULL_PLAN.json) were frozen and pushed (669665e) before any call
with seeds 4-6 on coding-hard-v1 (24 evaluation tasks x 3 fresh seeds = 72 cases, agent seed offset 1700, so every
agent sample is new). Inkling-2-Mini on Spark_01..04 (mem fraction 0.75), 8 independent 32K `code_xl` agents per case,
20 agents per node, each arm alone on the fleet with server-side token counting and GPU-rail energy. Proposals are
graded in the CPU sandbox on public feedback cases (used by the controller) and hidden holdout cases (scoring only).

- **F**: all 8 agents run to the end; answer = first agent in slot order whose code passes all feedback cases
  (the rule of inkling-coding-hard-v1).
- **E**: the first proposal in time that passes all feedback cases ends the case; the other agents are terminated
  (shim closes the stream, SGLang aborts), queued ones never start.

## Result

{md}
- Early stop solved **{e['solved']}/72** vs {f['solved']} for the full run (paired +{w} / -{l}, p = {res['paired_stop_vs_full']['p']:.2g}) at
  **{(1 - res['ratios']['tokens']) * 100:.0f} % fewer server tokens**, **{(1 - res['ratios']['wall']) * 100:.0f} % less wall time** and
  {(1 - res['ratios']['energy']) * 100:.0f} % less GPU energy; the median case stopped after {e['stop_seconds']['median']} s.
- The noise-free part: inside F, on the very same proposals, taking the first passing proposal in **time** order
  solves {f['solved_time_rule']} vs {f['solved']} for slot order ({sel:+d}). The fastest passing proposal is the better pick here (the offline
  replay of seeds 1-3 found no difference, 69 vs 69); the rest of E vs F is run-to-run noise.
- Context: F's oracle (any agent passing feedback and holdout) is {f['oracle']}/72; One Inkling (agent 0) {f['one']}/72.

Frozen rule: early stop is adopted if the selection effect inside F >= -1, E tokens <= 0.80 x F and E wall < F:
{', '.join(f'{k} = {v}' for k, v in res['decision'].items())}.

{verdict}

Files: `run_coding_earlystop.py` (runner), `run_coding_agents.py` (baseline, unchanged), `inkling/coding_arms.py`
(arm driver), `inkling/report_coding_earlystop.py`, numbers in [report.json](report.json).
""")
    print(md)


if __name__ == '__main__':
    main()
