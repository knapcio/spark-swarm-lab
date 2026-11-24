#!/usr/bin/env python3
"""Report for deepseek-coding3-v1 (DEEPSEEK_CODING3_PLAN.json): One DeepSeek V4.1 call per case vs the Inkling coding
swarm (coding-roll3-v1 R2 and R1) on the same 72 coding-hard-v1 cases (24 tasks x seeds 19-21).
Writes results/deepseek-coding3-v1/{REPORT.md, report.json}.

Per system: solved (/72), wrong (answered = passed the public feedback cases, but hidden tests fail), unanswered.
DeepSeek answers a case when its one proposal passes the feedback cases (the swarm's acceptance rule); it solves it
when that proposal also passes the hidden tests. Paired wins/losses DS vs R2 and DS vs R1 with the exact sign test.
Hybrid (per swarm arm): solved = swarm solved OR (swarm unanswered AND DS solved); wrong counted for both parts
(swarm wrong OR (swarm unanswered AND DS wrong)). Cost: DS client completion tokens per case, run wall from the DS
run's UTC timestamps (metadata started_utc / completed_utc), GPU Wh over that window from the node power logs
(inkling/energy.py window(), as inkling/arms.py calls it), Wh per solved; swarm cost from each arm's
arm_accounting.json. Incomplete (no comparison) if any DS case has an infrastructure fault (run_agents72.
operational_fault), a case is missing, or the run did not complete. A failed energy read is reported, not hidden.

usage: report_ds_coding3.py [--root DIR] [--ds DIR] [--r2 DIR] [--r1 DIR] [--out DIR]
"""
import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import energy  # noqa: E402
from run_agents72 import operational_fault  # noqa: E402

STUDY = 'deepseek-coding3-v1'
CASES = 72


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n)


def load_ds(d):
    d = Path(d)
    if not (d / 'summary.json').exists():
        return dict(status='not run', dir=str(d))
    meta = json.loads((d / 'metadata.json').read_text()) if (d / 'metadata.json').exists() else {}
    rows = json.loads((d / 'summary.json').read_text())
    reasons = []
    faults = [f"{r['task_id']} s{r['seed']}: {operational_fault(r)}" for r in rows if operational_fault(r)]
    if faults:
        reasons.append(f'{len(faults)} DS case(s) with an infrastructure fault: {faults[:3]}')
    keys = [(r['task_id'], r['seed']) for r in rows]
    if len(set(keys)) != len(keys):
        reasons.append('a DS case appears twice')
    if len(set(keys)) != CASES:
        reasons.append(f'{len(set(keys))} DS cases recorded, {CASES} expected')
    if not meta.get('completed_utc') or meta.get('errors'):
        reasons.append('DS run not completed cleanly')
    cases = {(r['task_id'], r['seed']): dict(answered=bool(r.get('feedback_pass')),
                                             solved=bool(r.get('feedback_pass') and r.get('holdout_pass')),
                                             wrong=bool(r.get('feedback_pass') and not r.get('holdout_pass')),
                                             tokens=r.get('charged_completion_tokens', r.get('completion_tokens')) or 0)
             for r in rows}
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, dir=str(d), meta=meta, cases=cases)


def load_swarm(d):
    d = Path(d)
    if not (d / 'cases.json').exists():
        return dict(status='not run', dir=str(d))
    rows = json.loads((d / 'cases.json').read_text())
    cases = {(r['task_id'], r['seed']): dict(answered=bool(r.get('answered')), solved=bool(r.get('solved')),
                                             wrong=bool(r.get('answered') and not r.get('solved'))) for r in rows}
    acct = json.loads((d / 'arm_accounting.json').read_text()) if (d / 'arm_accounting.json').exists() else {}
    energy_rec = acct.get('energy') if isinstance(acct.get('energy'), dict) else {}
    reasons = [] if len(cases) == CASES else [f'{len(cases)} swarm cases, {CASES} expected']
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, dir=str(d), cases=cases,
                cost=dict(server_generation_tokens=((acct.get('server') or {}).get('total') or {}).get('generation_tokens'),
                          wall_seconds=acct.get('runner_wall_seconds'), wh=energy_rec.get('total_wh')))


def counts(cases):
    vals = list(cases.values())
    return dict(cases=len(vals), solved=sum(c['solved'] for c in vals), wrong=sum(c['wrong'] for c in vals),
                unanswered=sum(not c['answered'] for c in vals))


def ds_cost(ds, energy_window=None):
    meta, n = ds['meta'], len(ds['cases'])
    tokens = sum(c['tokens'] for c in ds['cases'].values())
    out = dict(client_completion_tokens=tokens, client_completion_tokens_per_case=tokens / n if n else None)
    try:
        start, end = datetime.fromisoformat(meta['started_utc']), datetime.fromisoformat(meta['completed_utc'])
        out['wall_seconds'] = (end - start).total_seconds()
    except (KeyError, TypeError, ValueError):
        out['wall_seconds'] = None
        return out
    try:
        window = (energy_window or energy.window)(meta['started_utc'], meta['completed_utc'])
        out['wh'] = window.get('total_wh')
        out['energy_nodes'] = window.get('nodes')
    except Exception as exc:  # reported, never silently zero
        out['wh'], out['energy_error'] = None, f'{type(exc).__name__}: {exc}'[:200]
    solved = sum(c['solved'] for c in ds['cases'].values())
    out['wh_per_solved'] = out['wh'] / solved if out.get('wh') is not None and solved else None
    return out


def paired(ds, sw):
    keys = sorted(set(ds) & set(sw))
    wins = sum(ds[k]['solved'] and not sw[k]['solved'] for k in keys)
    losses = sum(sw[k]['solved'] and not ds[k]['solved'] for k in keys)
    return dict(cases=len(keys), ds_only=wins, swarm_only=losses, sign_test_p=sign_test(wins, losses))


def hybrid(ds, sw):
    keys = sorted(set(ds) & set(sw))
    solved = sum(sw[k]['solved'] or (not sw[k]['answered'] and ds[k]['solved']) for k in keys)
    wrong = sum(sw[k]['wrong'] or (not sw[k]['answered'] and ds[k]['wrong']) for k in keys)
    return dict(cases=len(keys), solved=solved, wrong=wrong, ds_calls=sum(not sw[k]['answered'] for k in keys),
                unanswered=len(keys) - solved - wrong)


def build(root, dirs, energy_window=None):
    ds = load_ds(root / dirs['ds'])
    swarms = {k: load_swarm(root / dirs[k]) for k in ('r2', 'r1')}
    s = dict(study=STUDY, systems={'DS': {k: ds[k] for k in ('status', 'reasons', 'dir') if k in ds}})
    if 'cases' in ds:
        s['systems']['DS'].update(counts(ds['cases']))
    for k, sw in swarms.items():
        s['systems'][k.upper()] = {x: sw[x] for x in ('status', 'reasons', 'dir') if x in sw}
        if 'cases' in sw:
            s['systems'][k.upper()].update(counts(sw['cases']), cost=sw['cost'])
    complete = ds['status'] == 'complete' and all(sw['status'] == 'complete' for sw in swarms.values())
    s['status'] = 'complete' if complete else 'incomplete'
    if complete:
        s['systems']['DS']['cost'] = ds_cost(ds, energy_window)
        s['paired'] = {f'DS_vs_{k.upper()}': paired(ds['cases'], sw['cases']) for k, sw in swarms.items()}
        s['hybrid'] = {f'{k.upper()}+DS': hybrid(ds['cases'], sw['cases']) for k, sw in swarms.items()}
    return s


def fmt(v):
    if v is None:
        return '-'
    if isinstance(v, float):
        return f'{v:,.4g}' if abs(v) < 10 else f'{v:,.1f}'
    return f'{v:,}' if isinstance(v, int) else str(v)


def markdown(s):
    out = [f'# {STUDY}: One DeepSeek vs the Inkling coding swarm', '', f"Status: {s['status']}", '',
           '| system | status | solved | wrong | unanswered |', '|---|---|---|---|---|']
    for name, x in s['systems'].items():
        out.append(f"| {name} | {x['status']} | {fmt(x.get('solved'))}/{fmt(x.get('cases'))} | {fmt(x.get('wrong'))} | "
                   f"{fmt(x.get('unanswered'))} |")
    for name, x in s['systems'].items():
        if x.get('reasons'):
            out.append(f"\n{name} incomplete: {'; '.join(x['reasons'])}")
    if 'paired' in s:
        out += ['', '## Paired (exact sign test)', '']
        for k, p in s['paired'].items():
            out.append(f"- {k}: DS-only solved {p['ds_only']}, swarm-only {p['swarm_only']}, p = {p['sign_test_p']:.4g}")
        out += ['', '## Hybrid: swarm first, DeepSeek on the swarm\'s unanswered cases', '']
        for k, h in s['hybrid'].items():
            out.append(f"- {k}: solved {h['solved']}/{h['cases']}, wrong {h['wrong']}, DS calls {h['ds_calls']}")
        c = s['systems']['DS']['cost']
        out += ['', '## Cost', '', f"- DS: client completion tokens per case {fmt(c['client_completion_tokens_per_case'])}, "
                f"run wall {fmt(c['wall_seconds'])} s, GPU {fmt(c.get('wh'))} Wh, Wh per solved {fmt(c.get('wh_per_solved'))}"
                + (f" (energy error: {c['energy_error']})" if c.get('energy_error') else '')]
        for k in ('R2', 'R1'):
            sc = s['systems'][k]['cost']
            out.append(f"- {k}: server generated tokens per case "
                       f"{fmt(sc['server_generation_tokens'] / s['systems'][k]['cases'] if sc['server_generation_tokens'] else None)}, "
                       f"wall {fmt(sc['wall_seconds'])} s, GPU {fmt(sc['wh'])} Wh, Wh per solved "
                       f"{fmt(sc['wh'] / s['systems'][k]['solved'] if sc['wh'] and s['systems'][k]['solved'] else None)}")
    out += ['', 'Bundled differences (model, engine, one call vs a swarm); no causal model-size claim. DS tokens are '
                'client-side completion tokens; the swarm figures are server counters.', '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--ds', default=f'runs/{STUDY}')
    p.add_argument('--r2', default='runs/coding-roll3-v1-r2')
    p.add_argument('--r1', default='runs/coding-roll3-v1-r1')
    p.add_argument('--out', type=Path)
    a = p.parse_args(argv)
    root = a.root.resolve()
    s = build(root, dict(ds=a.ds, r2=a.r2, r1=a.r1))
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), status=s['status'])))
    return 0 if s['status'] == 'complete' else 3


if __name__ == '__main__':
    raise SystemExit(main())
