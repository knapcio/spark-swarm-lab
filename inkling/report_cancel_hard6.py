#!/usr/bin/env python3
"""Report for SWARM_CANCEL_HARD6_PLAN.json (study swarm-cancel-hard6-v1): deep4 (A) vs deep4cancel (B) vs waves2cancel (C)
on the fresh arithmetic-hard-v6 corpus. Reads runs/swarm-cancel-hard6-v1-<policy>[ -rN]/cases.jsonl and the
arm_accounting.json written by inkling/arms.py; writes results/swarm-cancel-hard6-v1/{REPORT.md, report.json}.

usage: report_cancel_hard6.py [--arm POLICY=DIR[,DIR...]]...   (default: one directory per arm, no resume segments)
"""
import argparse
import json
import statistics
from pathlib import Path

from report_hard4 import sign_test

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / 'runs'
OUT = ROOT / 'results' / 'swarm-cancel-hard6-v1'
STUDY = 'swarm-cancel-hard6-v1'
ARMS = [('A', 'deep4'), ('B', 'deep4cancel'), ('C', 'waves2cancel')]


def load(dirs):
    """Cases of one arm, keyed (task, seed); later segments (resumes) replace cases that had infra faults."""
    cases, acct = {}, []
    for d in dirs:
        for line in (RUNS / d / 'cases.jsonl').read_text().splitlines():
            r = json.loads(line)
            if 'error' not in r:
                cases[(r['task_id'], r['seed'])] = r
        path = RUNS / d / 'arm_accounting.json'
        if path.exists():
            acct.append(json.loads(path.read_text()))
    return cases, acct


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def answer_time_slot_order(r):
    """deep4: the slot-order answer is known once every lower slot has finished (and been judged) and the selected
    one is accepted; with no answer, at case end."""
    if r.get('selected_slot') is None:
        return r['case_seconds']
    ends = [a.get('judged_s', a.get('finished_s')) for a in r['agents'] if a['slot'] <= r['selected_slot']]
    return max(e for e in ends if e is not None)


def summarize(cases, acct):
    keys = sorted(cases)
    rows = [cases[k] for k in keys]
    n = len(rows)
    agents = [a for r in rows for a in r['agents']]
    judged = [a for a in agents if a['verdict'] is not None]
    server = {}
    for a in acct:
        for k, v in a['server']['total'].items():
            server[k] = server.get(k, 0) + v
    joules = sum((a['energy'] or {}).get('total_joules') or 0 for a in acct)
    wall = sum(a['runner_wall_seconds'] for a in acct)
    solved = sum(r['solved'] for r in rows)
    case_s = [r['case_seconds'] for r in rows]
    if rows and rows[0]['policy'] == 'deep4':
        answer_s = [answer_time_slot_order(r) for r in rows]
    else:
        answer_s = [r['answer_seconds'] if r.get('answer_seconds') is not None else r['case_seconds'] for r in rows]
    return dict(
        cases=n, solved=solved, wrong=sum(r['wrong'] for r in rows), abstain=sum(not r['answered'] for r in rows),
        oracle=sum(r['oracle'] for r in rows), infra=sum(r['infra'] for r in rows),
        one_agent0=sum(bool(r['agents'][0]['verifier_solved']) for r in rows if r['agents'] and r['agents'][0]['slot'] == 0),
        server_generation_tokens=server.get('generation_tokens'), server_decode_tokens=server.get('decode_tokens'),
        server_prompt_tokens=server.get('prompt_tokens'), server_requests=server.get('requests'),
        shim_client_cancels=server.get('shim_client_cancels'), shim_upstream_errors=server.get('shim_upstream_errors'),
        server_tokens_per_case=round(server['generation_tokens'] / n) if n and server.get('generation_tokens') else None,
        client_tokens_per_case=round(sum(r['tokens'] for r in rows) / n) if n else None,
        arm_wall_seconds=round(wall), segments=len(acct),
        energy_wh=round(joules / 3600, 1) if joules else None,
        energy_wh_per_solved=round(joules / 3600 / solved, 2) if joules and solved else None,
        energy_wh_per_case=round(joules / 3600 / n, 2) if joules and n else None,
        case_seconds=dict(median=round(statistics.median(case_s)), p90=round(pct(case_s, .9)), max=round(max(case_s))),
        answer_seconds=dict(median=round(statistics.median(answer_s)), p90=round(pct(answer_s, .9)), max=round(max(answer_s))),
        agents_started=sum(a.get('started', True) for a in agents) + 0,
        agents_cancelled=sum(a.get('cancelled', False) for a in agents),
        agents_unstarted=sum(r.get('unstarted_agents', 0) for r in rows),
        judges_skipped=sum(a.get('judge_skipped', False) for a in agents),
        verdicts=len(judged), false_accepts=sum(a['verdict'] is True and not a['verifier_solved'] for a in judged),
        false_rejects=sum(a['verdict'] is False and a['verifier_solved'] for a in judged),
        deadlines=sum(r['deadlines'] for r in rows))


def paired(x, y):
    keys = sorted(set(x) & set(y))
    w = sum(x[k]['solved'] and not y[k]['solved'] for k in keys)
    l = sum(y[k]['solved'] and not x[k]['solved'] for k in keys)
    return dict(pairs=len(keys), wins=w, losses=l, p=sign_test(w, l))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arm', action='append', default=[], help='POLICY=DIR[,DIR...] (resume segments in order)')
    a = p.parse_args(argv)
    dirs = {pol: [f'{STUDY}-{pol}'] for _, pol in ARMS}
    for spec in a.arm:
        pol, ds = spec.split('=', 1)
        dirs[pol] = ds.split(',')
    data = {pol: load(ds) for pol, ds in dirs.items() if (RUNS / ds[0] / 'cases.jsonl').exists()}
    res = dict(study=STUDY, dirs=dirs, arms={pol: summarize(*data[pol]) for pol in data}, paired={})
    base = data.get('deep4')
    for pol in ('deep4cancel', 'waves2cancel'):
        if base and pol in data:
            res['paired'][f'{pol}_vs_deep4'] = paired(data[pol][0], base[0])
    if 'deep4cancel' in data and 'waves2cancel' in data:
        res['paired']['waves2cancel_vs_deep4cancel'] = paired(data['waves2cancel'][0], data['deep4cancel'][0])
    A = res['arms'].get('deep4')
    for pol, s in res['arms'].items():
        if A and pol != 'deep4' and A['server_generation_tokens'] and s['server_generation_tokens']:
            s['vs_deep4'] = dict(
                server_tokens_ratio=round(s['server_generation_tokens'] / A['server_generation_tokens'], 3),
                wall_ratio=round(s['arm_wall_seconds'] / A['arm_wall_seconds'], 3),
                energy_ratio=round(s['energy_wh'] / A['energy_wh'], 3) if s['energy_wh'] and A['energy_wh'] else None,
                non_inferior=s['solved'] >= A['solved'] - 2 and s['wrong'] == 0)
    if A and 'deep4cancel' in res['arms'] and 'vs_deep4' in res['arms']['deep4cancel']:
        v = res['arms']['deep4cancel']['vs_deep4']
        res['decision'] = dict(non_inferior=v['non_inferior'], tokens_at_least_15pct_lower=v['server_tokens_ratio'] <= .85,
                               wall_not_higher=v['wall_ratio'] <= 1.0)
        res['decision']['adopt_deep4cancel'] = all(res['decision'].values())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    print(json.dumps(res, indent=1))
    return res


if __name__ == '__main__':
    main()
