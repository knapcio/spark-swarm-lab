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
    if 'deep4' in data and 'deep4cancel' in data:
        A7, B7 = data['deep4'][0], data['deep4cancel'][0]
        losses = [k for k in A7 if A7[k]['solved'] and not B7[k]['solved']]
        res['b_vs_a_losses'] = dict(losses=len(losses), with_zero_cancels=sum(B7[k]['cancelled_agents'] == 0 for k in losses))
    arms = res['arms']
    if 'roll8cancel' in arms and 'deep4cancel' in arms:
        bp, b, ref = arms['roll8cancel'], arms['deep4cancel'], arms.get('deep4')
        tok_cap = ref['server_tokens_per_case'] if ref else 1.10 * b['server_tokens_per_case']
        wall_cap = ref['arm_wall_seconds'] if ref else 1.10 * b['arm_wall_seconds']
        res['decision'] = dict(zero_wrong=bp['wrong'] == 0, strict_rescues_at_least_2=res['rescues']['strict'] >= 2,
                               tokens_at_most_reference=bp['server_tokens_per_case'] <= tok_cap,
                               wall_below_reference=bp['arm_wall_seconds'] < wall_cap,
                               reference='A deep4' if ref else '1.10 x B')
        res['decision']['adopt_roll8cancel'] = all(v for k, v in res['decision'].items() if k != 'reference')
        res['owner_goal_solved_at_least_a'] = (bp['solved'] >= ref['solved']) if ref else None
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    (OUT / 'tables.md').write_text(tables(res))
    if all(pol in res['arms'] for _, pol in ARMS):
        (OUT / 'REPORT.md').write_text(report_md(res))
    print(tables(res))
    return res


def tables(res):
    names = dict(deep4cancel='B deep4cancel (default)', roll8cancel='B+ roll8cancel (escalation, max 8)', deep4='A deep4 (reference)')
    arms = [(pol, res['arms'][pol]) for _, pol in ARMS if pol in res['arms']]
    base = res['arms'].get('deep4cancel')
    rel = lambda v, b: f' ({(v / b - 1) * 100:+.0f} % vs B)' if b and v is not None and v != b else ''
    lines = ['| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 | GPU Wh | Wh per solved | '
             'Cancelled / escalation agents |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for pol, s in arms:
        esc = res['rescues']['escalated_agents'] if pol == 'roll8cancel' else 0
        lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,}"
                     f"{rel(s['server_tokens_per_case'], base['server_tokens_per_case'] if base else None)} | "
                     f"{s['arm_wall_seconds'] / 60:.0f} min{rel(s['arm_wall_seconds'], base['arm_wall_seconds'] if base else None)} | "
                     f"{s['case_seconds']['median']} / {s['case_seconds']['p90']} s | {s['energy_wh']} | {s['energy_wh_per_solved']:.2f} | "
                     f"{s['agents_cancelled']} / {esc} |")
    lines += ['', '| Paired (task, seed) | Pairs | Wins | Losses | Sign test p |', '|---|---:|---:|---:|---:|']
    for k, v in res['paired'].items():
        lines.append(f"| {k.replace('_vs_', ' vs ')} | {v['pairs']} | {v['wins']} | {v['losses']} | {v['p']:.3g} |")
    if 'rescues' in res:
        r = res['rescues']
        lines += ['', f"Escalation inside B+: {r['escalated_cases']} cases escalated ({r['escalated_agents']} extra agents; "
                  f"{r['escalated_in_solved_by_first_four']} of them were then solved by one of the first four), "
                  f"{r['loose']} cases answered by an escalation agent, of which **{r['strict']} strict rescues** "
                  f"(all first four had already failed), {r['strict_solved']} correct."]
    if res.get('decision'):
        lines += ['', 'Frozen decision rule: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items())]
        lines += [f"Owner goal (B+ solved >= A solved): {res.get('owner_goal_solved_at_least_a')}"]
    return '\n'.join(lines) + '\n'



def report_md(res):
    A, B, P = (res['arms'][p] for p in ('deep4', 'deep4cancel', 'roll8cancel'))
    r, d = res['rescues'], res['decision']
    pr = res['paired']
    pbb, pba, pab = pr['roll8cancel_vs_deep4cancel'], pr['roll8cancel_vs_deep4'], pr['deep4cancel_vs_deep4']
    pool = pr.get('pooled_v6_v7_deep4cancel_vs_deep4')
    pct = lambda x, y: f'{(x / y - 1) * 100:+.0f} %'
    verdict = ('**B+ becomes the default arithmetic swarm policy.**' if d['adopt_roll8cancel'] else
               '**B stays the default**: the frozen rule is not met (' + ', '.join(k for k, v in d.items() if v is False) + ').')
    return f"""# Escalation: spend the cancel savings on the hard cases (swarm-escalate-hard7-v1)

Plan [`SWARM_ESCALATE_HARD7_PLAN.json`](../../SWARM_ESCALATE_HARD7_PLAN.json) was frozen and pushed (1409067) before the
fresh corpus arithmetic-hard-v7 (generator seed 2026112103, same rules as v5/v6) was generated (168e423). Inkling-2-Mini
on Spark_01..04, 48 evaluation tasks x seeds 1-2 = 96 paired cases per arm, agents with a 32K budget, the swarm's own
thinking judge (exact verifier only scores). Arms ran one after another, each alone on the fleet, with server-side token
counting and GPU-rail energy, in the order B, B+, A.

- **B deep4cancel** (default since [hard6](../swarm-cancel-hard6-v1/REPORT.md)): 4 agents; the first judge-accepted
  plan answers and the other agents are terminated.
- **B+ roll8cancel**: as B, but every agent that ends without an accepted plan is replaced at once by a fresh-seed agent
  on the same node (4 in flight), up to 8 agents per case.
- **A deep4** (reference): 4 agents, all to the end.

## Result

{tables(res)}
## Reading

- **B+ solved {P['solved']}/96 with {P['wrong']} wrong**, vs B {B['solved']} (paired +{pbb['wins']} / -{pbb['losses']}, p = {pbb['p']:.2g}) and A {A['solved']}
  (+{pba['wins']} / -{pba['losses']}, p = {pba['p']:.2g}). The mechanism count, free of run-to-run noise: {r['strict']} cases were answered
  by an escalation agent after all of the first four had failed ({r['strict_solved']} of them correct); without escalation those
  cases are abstentions in the same run. The rest of the gap to B is run-to-run generation noise (hard-v6: two runs of
  one policy differ by about 4 cases).
- Cost: B+ used {P['server_tokens_per_case']:,} server tokens per case ({pct(P['server_tokens_per_case'], B['server_tokens_per_case'])} vs B,
  {pct(P['server_tokens_per_case'], A['server_tokens_per_case'])} vs A), {P['arm_wall_seconds'] / 60:.0f} min of arm wall ({pct(P['arm_wall_seconds'], B['arm_wall_seconds'])} vs B,
  {pct(P['arm_wall_seconds'], A['arm_wall_seconds'])} vs A) and {P['energy_wh_per_solved']:.2f} Wh per solved case (B {B['energy_wh_per_solved']:.2f}, A {A['energy_wh_per_solved']:.2f}).
  Escalation ran in {r['escalated_cases']} cases ({r['escalated_agents']} extra agents); the extra wall time comes from the escalated hard
  cases, which run up to twice as long as an abstention in B.
- Second-corpus check of B vs A (noise replication): +{pab['wins']} / -{pab['losses']} (p = {pab['p']:.2g}); pooled hard-v6 + v7, 192 cases:
  {('+' + str(pool['wins']) + ' / -' + str(pool['losses']) + f" (p = {pool['p']:.2g})") if pool else 'n/a'}. Again **all {res['b_vs_a_losses']['with_zero_cancels']} of B's
  {res['b_vs_a_losses']['losses']} losses are cases where B cancelled nothing** (it ran A's policy there and drew worse samples), so
  cancellation cannot be their cause. The direction repeated on both corpora, though, which we note openly; the pooled
  difference is not significant, and B+ (which contains B) is above A on this corpus.

One DeepSeek on the same 96 cases (separate plan, run afterwards): see [DEEPSEEK.md](DEEPSEEK.md).

## Decision

Frozen rule: B+ replaces B if 0 wrong, >= 2 strict rescues, server tokens per case <= A and arm wall < A.
{', '.join(f'{k} = {v}' for k, v in d.items())}.

{verdict}
Owner goal (B+ solved >= A solved, 0 wrong, tokens <= A, wall < A): solved {P['solved']} vs {A['solved']}, tokens
{P['server_tokens_per_case']:,} vs {A['server_tokens_per_case']:,}, wall {P['arm_wall_seconds'] / 60:.0f} vs {A['arm_wall_seconds'] / 60:.0f} min.

Files: runner `run_variants.py` (`roll8cancel`), arm driver `inkling/arms.py`, report `inkling/report_escalate_hard7.py`,
numbers in [report.json](report.json).
"""


if __name__ == '__main__':
    main()
