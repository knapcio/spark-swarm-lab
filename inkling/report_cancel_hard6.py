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
    if 'deep4' in data and 'deep4cancel' in data:
        res['noise'] = noise(dirs)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    (OUT / 'tables.md').write_text(tables(res))
    if all(pol in res['arms'] for _, pol in ARMS):
        (OUT / 'REPORT.md').write_text(report_md(res))
    print(tables(res))
    return res


def noise(dirs):
    """Run-to-run noise between A and B where B cancelled nothing: same-seed agents that ran to the end in both arms."""
    A, _ = load(dirs['deep4'])
    B, _ = load(dirs['deep4cancel'])
    pairs = flips = a_only = b_only = same_tokens = 0
    for k in A:
        for a in A[k]['agents']:
            b = next((x for x in B[k]['agents'] if x['slot'] == a['slot']), None)
            if b is None or b.get('cancelled') or not b.get('started', True):
                continue
            pairs += 1
            same_tokens += a['tokens'] == b['tokens']
            if a['verifier_solved'] != b['verifier_solved']:
                flips += 1
                a_only += bool(a['verifier_solved'])
                b_only += bool(b['verifier_solved'])
    zero = [k for k in A if B[k]['cancelled_agents'] == 0 and B[k].get('unstarted_agents', 0) == 0]
    losses = [k for k in A if A[k]['solved'] and not B[k]['solved']]
    abst = {name: [k for k in X if not X[k]['answered']] for name, X in (('A', A), ('B', B))}
    return dict(agent_pairs_completed_in_both=pairs, agent_outcome_flips=flips, flips_a_only=a_only, flips_b_only=b_only,
                identical_token_counts=same_tokens, cases_without_cancel_in_b=len(zero),
                case_flips_without_cancel=sum(A[k]['solved'] != B[k]['solved'] for k in zero),
                b_losses=len(losses), b_losses_with_zero_cancels=sum(B[k]['cancelled_agents'] == 0 for k in losses),
                b_cases_with_cancels=sum(B[k]['cancelled_agents'] > 0 for k in B),
                b_cases_with_cancels_solved=sum(B[k]['cancelled_agents'] > 0 and B[k]['solved'] for k in B),
                abstentions=dict(A=len(abst['A']), B=len(abst['B'])),
                abstentions_with_rejected_plan=sum(any(a['verdict'] is False for a in X[k]['agents'])
                                                   for name, X in (('A', A), ('B', B)) for k in abst[name]),
                abstentions_solved_by_other_arm=sum(B[k]['solved'] for k in abst['A']) + sum(A[k]['solved'] for k in abst['B']),
                abstained_in_both=sum(not B[k]['answered'] for k in abst['A']))


def tables(res):
    names = dict(deep4='A deep4', deep4cancel='B deep4cancel', waves2cancel='C waves2cancel')
    arms = [(pol, res['arms'][pol]) for _, pol in ARMS if pol in res['arms']]
    fmt = lambda v, f='{:,}': '' if v is None else f.format(v)
    rat = lambda s, k: f" ({s['vs_deep4'][k] - 1:+.0%})" if s.get('vs_deep4') and s['vs_deep4'].get(k) else ''
    lines = ['| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Client tokens/case | Arm wall | '
             'Case wall median / p90 | Answer time median / p90 | GPU Wh | Wh per solved | Cancelled / never started agents |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for pol, s in arms:
        lines.append(f"| {names[pol]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | "
                     f"{fmt(s['server_tokens_per_case'])}{rat(s, 'server_tokens_ratio')} | {fmt(s['client_tokens_per_case'])} | "
                     f"{s['arm_wall_seconds'] / 60:.0f} min{rat(s, 'wall_ratio')} | "
                     f"{s['case_seconds']['median']} / {s['case_seconds']['p90']} s | {s['answer_seconds']['median']} / {s['answer_seconds']['p90']} s | "
                     f"{fmt(s['energy_wh'])}{rat(s, 'energy_ratio')} | {fmt(s['energy_wh_per_solved'])} | "
                     f"{s['agents_cancelled']} / {s['agents_unstarted']} |")
    lines += ['', '| Paired (task, seed) | Pairs | Wins | Losses | Sign test p |', '|---|---:|---:|---:|---:|']
    for k, v in res['paired'].items():
        lines.append(f"| {k.replace('_vs_', ' vs ')} | {v['pairs']} | {v['wins']} | {v['losses']} | {v['p']:.3g} |")
    lines += ['', '| Arm | Oracle | One Inkling (agent 0) | Judge verdicts | False accepts | False rejects | Skipped judges | '
              'Deadlines | Infra | Shim client cancels | Shim upstream errors | Segments |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for pol, s in arms:
        lines.append(f"| {names[pol]} | {s['oracle']} | {s['one_agent0']} | {s['verdicts']} | {s['false_accepts']} | "
                     f"{s['false_rejects']} | {s['judges_skipped']} | {s['deadlines']} | {s['infra']} | "
                     f"{fmt(s['shim_client_cancels'], '{:.0f}')} | {fmt(s['shim_upstream_errors'], '{:.0f}')} | {s['segments']} |")
    if res.get('decision'):
        lines += ['', 'Frozen decision rule, applied literally: ' + ', '.join(f'{k} = {v}' for k, v in res['decision'].items())]
    return '\n'.join(lines) + '\n'



def report_md(res):
    A, B, C = (res['arms'][p] for p in ('deep4', 'deep4cancel', 'waves2cancel'))
    n, pb, pc = res['noise'], res['paired']['deep4cancel_vs_deep4'], res['paired']['waves2cancel_vs_deep4']
    vb, vc = B['vs_deep4'], C['vs_deep4']
    pct = lambda r: f'{(r - 1) * 100:+.0f} %'
    cut = lambda r: f'{(1 - r) * 100:.0f} %'
    coding = CODING
    return f"""# Cancel the other agents once one plan is accepted (swarm-cancel-hard6-v1)

Plan [`SWARM_CANCEL_HARD6_PLAN.json`](../../SWARM_CANCEL_HARD6_PLAN.json) was frozen and pushed (2376372, code 8f0bc59)
before the fresh corpus arithmetic-hard-v6 (generator seed 2026112102, same rules as hard-v5) was generated (d8bc18e).
Inkling-2-Mini on Spark_01..04, 48 evaluation tasks x seeds 1-2 = 96 paired cases per arm, 4 agents with a 32K budget,
the swarm's own thinking judge, exact verifier for scoring only. Arms ran one after another, each alone on the fleet
(admission, prefix-cache flush, server counters before and after, GPU-rail energy from the 1 Hz logs).

- **A deep4**: 4 agents, all run to the end, first judge-accepted plan in slot order (the previous default).
- **B deep4cancel**: 4 agents; the first judge-accepted plan in time answers the case and the other agents are
  terminated at once (process group killed, the shim closes the upstream stream, SGLang aborts the request in < 0.5 s).
- **C waves2cancel**: agents 0+1 with the B rule; agents 2+3 only if neither was accepted (40 cases at once to keep
  the same ~20 agents per node).

## Result

{tables(res)}
Server tokens = delta of `sglang:generation_tokens_total` on the four nodes over the arm window (it includes the tokens
of aborted requests; verified with a killed client before the study). Client tokens miss the work of terminated agents,
so the server count is the one that matters. In A they agree exactly ({A['server_tokens_per_case']:,} per case), which
validates the counter. Answer time for A = when the slot-order answer is known (all lower slots finished and judged).

## Verdict: B is accuracy-neutral by mechanism and becomes the default

B cut **server tokens by {cut(vb['server_tokens_ratio'])}**, **arm wall time by {cut(vb['wall_ratio'])}** and
**GPU energy by {cut(vb['energy_ratio'])}** ({B['energy_wh_per_solved']:.2f} vs {A['energy_wh_per_solved']:.2f} Wh per solved case);
the median case finished in {B['case_seconds']['median']} s instead of {A['case_seconds']['median']} s. It gave
{B['wrong']} wrong answers.

Honest reading of the pre-registered rule: B solved {B['solved']} vs A {A['solved']} (paired +{pb['wins']} / -{pb['losses']},
sign test p = {pb['p']:.2g}). The frozen non-inferiority margin was B >= A - 2 = {A['solved'] - 2}, so **the margin was
missed by {A['solved'] - 2 - B['solved']}** and the frozen decision rule says "not adopted".

The mechanism says the loss is not caused by cancelling:
- **All {n['b_losses_with_zero_cancels']} of B's losses (of {n['b_losses']}) are cases where B cancelled nothing.** There B ran the same four agents
  to the end and judged every plan, exactly like A; it simply drew worse samples.
- In every case where B did cancel ({n['b_cases_with_cancels']} cases) the answer had already been accepted by the judge, which made
  0 false accepts in {A['verdicts'] + B['verdicts'] + C['verdicts']} verdicts here (and 0 in 330 on hard-v4). Cancelling cannot change
  such a case; B solved all {n['b_cases_with_cancels_solved']} of them.
- **Two identical-configuration runs differ by a few cases.** Same-seed agents do not reproduce across runs (batched
  numerics on the server): of the {n['agent_pairs_completed_in_both']} agents that ran to the end in both A and B with the same seed, only
  {n['identical_token_counts']} produced the same number of tokens and **{n['agent_outcome_flips']} ({n['agent_outcome_flips'] / n['agent_pairs_completed_in_both']:.0%}) changed outcome**
  ({n['flips_a_only']} solved only in A, {n['flips_b_only']} only in B). On the {n['cases_without_cancel_in_b']} cases where B cancelled nothing (so B ran the A policy), {n['case_flips_without_cancel']}
  case outcomes flipped. A 3-case difference between two runs of the same policy is ordinary.

Decision (owner, 2026-11-21, on this evidence): **deep4cancel is the default arithmetic swarm policy**; later studies
build on it. A confirmatory check of B against A on a second fresh corpus is part of the next study.

C (waves of 2) solved {C['solved']} with {C['wrong']} wrong (vs A +{pc['wins']} / -{pc['losses']}, p = {pc['p']:.2g}) at
{pct(vc['server_tokens_ratio'])} server tokens, {pct(vc['wall_ratio'])} arm wall and {pct(vc['energy_ratio'])} energy vs A
(secondary arm; it changes no decision). Waves save the most tokens but stretch the hard cases: its p90 case time
was {C['case_seconds']['p90']} s vs {A['case_seconds']['p90']} s for A, and it lost more cases than B, so it is not pursued.

One DeepSeek on the same 96 cases (separate plan, run afterwards): see [DEEPSEEK.md](DEEPSEEK.md).

## Abstentions: what more agents could buy

All {n['abstentions_with_rejected_plan']} abstentions (A {n['abstentions']['A']}, B {n['abstentions']['B']}) had at least one judged and rejected plan. On those cases the other
arm's four fresh agents solved {n['abstentions_solved_by_other_arm']} of {n['abstentions']['A'] + n['abstentions']['B']}; {n['abstained_in_both']} cases abstained in both arms. So about one abstention in
five is solvable by four more agents; this calibrates the next study (B plus adaptive escalation on a fresh corpus).

## Shim change and cancellation check

`inkling/shim.py` now treats a client that closes its stream as a cancellation: it closes the upstream SGLang stream at
once and counts `shim:client_cancels`, not `shim:upstream_errors` (the watchdog alerts on the latter). Before the study,
on each Spark a streamed thinking completion was killed after 8-10 s: `sglang:num_running_reqs` fell to 0 within 0.5 s,
`client_cancels` = 1, `upstream_errors` = 0, and `generation_tokens_total` included the aborted tokens. The old shim also
freed the server but counted the disconnect as an upstream error. In B, {B['shim_client_cancels']:.0f} cancellations,
0 upstream errors.

{coding}
## Files

Runner `run_variants.py` (`deep4cancel`, `waves2cancel`, `--policy`; the cancellable executor lives here because
`run_benchmark.py` is hash-pinned by earlier frozen plans), arm driver `inkling/arms.py`, report
`inkling/report_cancel_hard6.py`, accounting per arm in `runs/swarm-cancel-hard6-v1-*/arm_accounting.json` (not in git),
numbers in [report.json](report.json).
"""


CODING = "## Exploratory: the same idea for the coding swarm (offline, post hoc)\n\nReplay of the recorded coding swarm (coding-hard-v1, 72 cases, 8 agents of 32K; runs `inkling-coding-hard-v1` + `v1b`)\nwith [`inkling/sim_coding_early_stop.py`](../../inkling/sim_coding_early_stop.py) ([sim.json](../inkling-coding-early-stop-sim/sim.json)).\nNo model, sandbox or fleet calls; same data as the 69/72 (first feedback-passing) and 70/72 (executable disproofs)\nresults, so a hypothesis only. Baseline reproduced exactly (69, 70, 101,889 completion tokens per case). Policy: stop\nthe case when the first candidate **in time order** passes the public tests and is not disproved by the case's contract;\ntokens of agents still generating at the stop are interpolated inside their current request (estimate).\n\n| Variant | Solved /72 | Tokens/case, recorded timeline | Saved | All 8 start at t=0 | Saved | Case wall saved |\n|---|---:|---:|---:|---:|---:|---:|\n| All 8 to the end (original / disproof rule) | 69 / 70 | 101,889 (+13,273 contract) | | | | |\n| Stop at first feedback-passing | 69 | 55,640 | 45 % | 66,600 | 35 % | 61 % / 55 % |\n| Stop at first feedback-passing, not disproved | 69 | 56,600 + contract | 44 % (31 % incl. contract) | 67,300 + contract | 34 % (21 %) | 61 % / 55 % |\n| Same, not before the contract is ready | 69 | 67,300 + contract | 34 % (21 %) | 80,600 + contract | 21 % (8 %) | 49 % / 38 % |\n\n- Every early-stop variant gives **69/72**: original accuracy kept, the disproof gain (70) lost. Lost\n  `eva-date_diff_ymd-s3` and `eva-monthly_occurrences-s1` (the first finisher passed the public tests, was not disproved\n  and failed the hidden holdout); gained `eva-shell_words-s1` (already fixed by disproofs) and `eva-shell_words-s2`.\n- About a third fewer tokens if all agents start together; the contract call (13.3K tokens, median 622 s) eats much of it.\n- Unlike arithmetic, where acceptance is an independent judge with 0 false accepts, the coding stop signal lets wrong\n  candidates through, and the fastest finisher is not safer. Expected live outcome: 69 for about a third fewer tokens,\n  not 70 for less. Needs a frozen plan on fresh tasks before any claim.\n"


if __name__ == '__main__':
    main()
