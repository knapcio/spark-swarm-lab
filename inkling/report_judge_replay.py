#!/usr/bin/env python3
"""Report for the judge replay screens (judge_replay.py): what a second acceptance key would have done to recorded
candidates. Writes OUT/{REPORT.md, report.json}.

  coding (--coding DIR)  generic protocol judge on recorded coding winners: wrong winners (hidden tests fail) the judge
                         rejects (wanted) vs correct winners it rejects (false rejects, each a lost answer)
  arith  (--arith DIR)   second arithmetic judge: valid forced plans it rejects (lost rescues), valid control plans it
                         rejects (baseline), and, if present, rejected forced plans it accepts (false accepts)
Complete only if a part's run finished (metadata completed, every candidate judged once, no judge fault) and its
account_cmd record is clean (shared validation of report_round3_hard17); otherwise that part is 'incomplete' with the
reasons. Costs: client judge tokens and the server counters of the part's account_cmd record (generated, prompt,
computed prefill, Wh). A verdict of None (no parseable answer) is reported separately and counted as neither.

usage: report_judge_replay.py [--coding DIR] [--arith DIR] [--plan PLAN] --out DIR
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_relay  # noqa: E402  (server_work)
import report_round3_hard17 as r3  # noqa: E402


def load(d):
    d = Path(d)
    if not (d / 'candidates.jsonl').exists():
        return dict(status='not run', dir=str(d))
    meta = json.loads((d / 'metadata.json').read_text()) if (d / 'metadata.json').exists() else {}
    rows = r3.round3_gate.read_rows(d / 'candidates.jsonl')
    reasons = []
    if not meta.get('completed_utc'):
        reasons.append('run not completed')
    if meta.get('candidates') is not None and len(rows) != meta['candidates']:
        reasons.append(f"{len(rows)} judged of {meta['candidates']} candidates")
    keys = [(r['run'], r['task_id'], r['seed'], r.get('agent', r.get('slot')), r.get('policy')) for r in rows]
    if len(set(keys)) != len(keys):
        reasons.append('a candidate was judged twice')
    faults = sum(bool(r.get('infra')) or 'error' in r for r in rows)
    if faults:
        reasons.append(f'{faults} candidate(s) with a judge fault')
    acct = r3.accounting([d], wrapper=True)
    reasons += acct['accounting_problems']
    work, problems = report_relay.server_work(d)
    reasons += problems
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, dir=str(d), meta=meta, rows=rows,
                server=dict(work, wh=acct['wh'], window_seconds=acct['window_seconds']),
                client_tokens=sum(r.get('tokens') or 0 for r in rows))


def table(rows):
    """{group: {truth: {verdict: n}}} with verdicts True / False / None."""
    out = {}
    for r in rows:
        g = out.setdefault(r['group'], {'correct': Counter(), 'wrong': Counter()})
        g['correct' if r['truth'] else 'wrong'][str(r['verdict'])] += 1
    return {g: {t: dict(c) for t, c in v.items()} for g, v in out.items()}


def coding_facts(rows):
    wrong = [r for r in rows if not r['truth']]
    correct = [r for r in rows if r['truth']]
    return dict(winners=len(rows), wrong_winners=len(wrong), correct_winners=len(correct),
                wrong_rejected=sum(r['verdict'] is False for r in wrong),
                wrong_accepted=sum(r['verdict'] is True for r in wrong),
                correct_rejected=sum(r['verdict'] is False for r in correct),
                correct_accepted=sum(r['verdict'] is True for r in correct),
                no_verdict=sum(r['verdict'] is None for r in rows),
                wrong_rejected_tasks=sorted({r['task_id'] for r in wrong if r['verdict'] is False}),
                correct_rejected_by_task=dict(Counter(r['task_id'] for r in correct if r['verdict'] is False)),
                forced_winners=sum(bool(r.get('forced')) for r in rows))


def arith_facts(rows):
    by = lambda g: [r for r in rows if r['group'] == g]
    out = {}
    for g in ('forced', 'control'):
        rs = by(g)
        out[g] = dict(plans=len(rs), valid=sum(r['truth'] for r in rs),
                      valid_rejected=sum(r['truth'] and r['verdict'] is False for r in rs),
                      invalid_accepted=sum((not r['truth']) and r['verdict'] is True for r in rs),
                      no_verdict=sum(r['verdict'] is None for r in rs))
    rej = by('forced_rejected')
    if rej:
        out['forced_rejected'] = dict(plans=len(rej), invalid=sum(not r['truth'] for r in rej),
                                      false_accepts=sum((not r['truth']) and r['verdict'] is True for r in rej),
                                      valid_accepted=sum(r['truth'] and r['verdict'] is True for r in rej),
                                      no_verdict=sum(r['verdict'] is None for r in rej))
    return out


def build(coding_dir, arith_dir, plan_file=None):
    s = dict(parts={})
    for name, d, facts in (('coding', coding_dir, coding_facts), ('arith', arith_dir, arith_facts)):
        if d is None:
            continue
        a = load(d)
        part = {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
        if 'rows' in a:
            part.update(table=table(a['rows']), client_tokens=a['client_tokens'], server=a['server'],
                        facts=facts(a['rows']) if a['status'] == 'complete' else None)
        s['parts'][name] = part
    plan = json.loads(Path(plan_file).read_text()) if plan_file and Path(plan_file).exists() else {}
    s['decision_rule'] = plan.get('decision_rule', 'not given')
    s['disclosure'] = r3.disclosure()
    return s


def markdown(s):
    fmt = r3.fmt
    out = ['# Judge replay screens', '']
    c = s['parts'].get('coding')
    if c:
        out += ['## Coding: generic judge as a second acceptance key', '', f"Status: {c['status']}"]
        if c.get('reasons'):
            out.append(f"Incomplete: {'; '.join(c['reasons'])}")
        f = c.get('facts')
        if f:
            out += ['', f"- wrong winners (hidden tests fail) rejected by the judge: {f['wrong_rejected']} of {f['wrong_winners']}"
                        f" (accepted {f['wrong_accepted']})",
                    f"- correct winners wrongly rejected: {f['correct_rejected']} of {f['correct_winners']}"
                    f" (by task: {f['correct_rejected_by_task']})",
                    f"- no parseable verdict: {f['no_verdict']}; forced winners: {f['forced_winners']}"]
        if 'server' in c:
            out.append(f"- cost: client judge tokens {fmt(c['client_tokens'])}; server generated "
                       f"{fmt(c['server'].get('generation_tokens'))}, prompt {fmt(c['server'].get('prompt_tokens'))}, "
                       f"prefill computed {fmt(c['server'].get('prefill_compute_tokens'))}, {fmt(c['server'].get('wh'))} Wh, "
                       f"{fmt(c['server'].get('window_seconds'))} s")
        out.append('')
    a = s['parts'].get('arith')
    if a:
        out += ['## Arithmetic: a second judge for forced answers', '', f"Status: {a['status']}"]
        if a.get('reasons'):
            out.append(f"Incomplete: {'; '.join(a['reasons'])}")
        f = a.get('facts')
        if f:
            for g in ('forced', 'control'):
                x = f[g]
                out.append(f"- {g}: {x['valid_rejected']} of {x['valid']} valid accepted plans rejected by the second judge "
                           f"({x['invalid_accepted']} invalid accepted, {x['no_verdict']} without verdict)")
            if 'forced_rejected' in f:
                x = f['forced_rejected']
                out.append(f"- forced plans the first judge rejected: false accepts by the second judge {x['false_accepts']} "
                           f"of {x['invalid']} invalid")
        if 'server' in a:
            out.append(f"- cost: client judge tokens {fmt(a['client_tokens'])}; server generated "
                       f"{fmt(a['server'].get('generation_tokens'))}, prompt {fmt(a['server'].get('prompt_tokens'))}, "
                       f"{fmt(a['server'].get('wh'))} Wh")
        out.append('')
    out += [f"Frozen rule: {s['decision_rule']}", '', '## Disclosures', '', s['disclosure'],
            '', 'The hidden-test / verifier results are copied from the recorded runs for scoring only.', '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--coding', type=Path)
    p.add_argument('--arith', type=Path)
    p.add_argument('--plan', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    if not (a.coding or a.arith):
        raise SystemExit('give --coding and/or --arith')
    s = build(a.coding, a.arith, a.plan)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (a.out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps({k: v['status'] for k, v in s['parts'].items()}))
    return 0 if all(v['status'] == 'complete' for v in s['parts'].values()) else 3


if __name__ == '__main__':
    raise SystemExit(main())
