#!/usr/bin/env python3
"""Report for SWARM_ESCALATE_HARD7_PLAN.json (study swarm-escalate-hard7-v1): B deep4cancel vs B+ roll8cancel
(adaptive escalation up to 8 agents) vs reference A deep4 on arithmetic-hard-v7. Writes
results/swarm-escalate-hard7-v1/{report.json, tables.md}; pooled hard-v6 + hard-v7 B vs A as a secondary check.

usage: report_escalate_hard7.py [--arm POLICY=DIR[,DIR...]]...
"""
import argparse
import json

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

STUDY = 'swarm-escalate-hard7-v1'
OUT = ROOT / 'results' / STUDY
ARMS = [('B', 'deep4cancel'), ('B+', 'roll8cancel'), ('A', 'deep4')]


def rescues(cases):
    """strict: answered by an escalation agent (slot >= 4) while none of the first four was still running (none of
    them was cancelled), i.e. without escalation the case would have been an abstention in this same run."""
    loose = [k for k, r in cases.items() if r.get('selected_slot') is not None and r['selected_slot'] >= 4]
    strict = [k for k in loose if not any(a['slot'] < 4 and a.get('cancelled') for a in cases[k]['agents'])]
    return dict(loose=len(loose), strict=len(strict), strict_solved=sum(cases[k]['solved'] for k in strict),
                strict_cases=[list(k) for k in strict],
                escalated_cases=sum(r.get('escalated_agents', 0) > 0 for r in cases.values()),
                escalated_agents=sum(r.get('escalated_agents', 0) for r in cases.values()),
                escalated_in_solved_by_first_four=sum(r.get('escalated_agents', 0) > 0 and r.get('selected_slot') is not None
                                                      and r['selected_slot'] < 4 for r in cases.values()))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arm', action='append', default=[])
    a = p.parse_args(argv)
    dirs = {pol: [f'{STUDY}-{pol}'] for _, pol in ARMS}
    for spec in a.arm:
        pol, ds = spec.split('=', 1)
        dirs[pol] = ds.split(',')
    data = {pol: load(ds) for pol, ds in dirs.items() if (RUNS / ds[0] / 'cases.jsonl').exists()}
    res = dict(study=STUDY, dirs=dirs, arms={pol: summarize(*data[pol]) for pol in data}, paired={})
    if 'roll8cancel' in data:
        res['rescues'] = rescues(data['roll8cancel'][0])
    for x, y in (('roll8cancel', 'deep4cancel'), ('roll8cancel', 'deep4'), ('deep4cancel', 'deep4')):
        if x in data and y in data:
            res['paired'][f'{x}_vs_{y}'] = paired(data[x][0], data[y][0])
    # secondary: pooled hard-v6 + hard-v7, B vs A
    if 'deep4' in data and 'deep4cancel' in data:
        a6, _ = load(['swarm-cancel-hard6-v1-deep4'])
        b6, _ = load(['swarm-cancel-hard6-v1-deep4cancel'])
        pa = {('v6',) + k: v for k, v in a6.items()} | {('v7',) + k: v for k, v in data['deep4'][0].items()}
        pb = {('v6',) + k: v for k, v in b6.items()} | {('v7',) + k: v for k, v in data['deep4cancel'][0].items()}
        res['paired']['pooled_v6_v7_deep4cancel_vs_deep4'] = paired(pb, pa)
    arms = res['arms']
    if 'roll8cancel' in arms and 'deep4cancel' in arms:
        bp, b, ref = arms['roll8cancel'], arms['deep4cancel'], arms.get('deep4')
        tok_cap = ref['server_generation_tokens'] if ref else 1.10 * b['server_generation_tokens']
        wall_cap = ref['arm_wall_seconds'] if ref else 1.10 * b['arm_wall_seconds']
        res['decision'] = dict(zero_wrong=bp['wrong'] == 0, strict_rescues_at_least_2=res['rescues']['strict'] >= 2,
                               tokens_at_most_reference=bp['server_generation_tokens'] <= tok_cap,
                               wall_below_reference=bp['arm_wall_seconds'] < wall_cap,
                               reference='A deep4' if ref else '1.10 x B')
        res['decision']['adopt_roll8cancel'] = all(v for k, v in res['decision'].items() if k != 'reference')
        res['owner_goal_solved_at_least_a'] = (bp['solved'] >= ref['solved']) if ref else None
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    print(json.dumps({k: v for k, v in res.items() if k != 'dirs'}, indent=1))
    return res


if __name__ == '__main__':
    main()
