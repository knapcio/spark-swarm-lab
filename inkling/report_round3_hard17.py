#!/usr/bin/env python3
"""Report for study swarm-round3-hard17-v1: default D vs leftover-sentence L, add-ons X (esc_extra, slots 12-19),
C (closers) and R (end-of-budget recall) on D's clean abstentions, and the two dev-screen gates.
Writes results/swarm-round3-hard17-v1/{REPORT.md, report.json}. Works mid-study: an arm without output is 'not run',
an arm whose segments do not yet cover its cases is 'incomplete'.

Inputs (paths relative to the repo root; override with the flags):
  D, L  runs/swarm-round3-hard17-v1-{d,l}-roll12strategy[-resumeN]   (run_variants via inkling/arms.py)
  X     runs/swarm-round3-hard17-v1-x-esc_extra[-resumeN]            (run_variants via inkling/arms.py)
  C     runs/swarm-round3-hard17-v1-c                                (closer_replay via inkling/account_cmd.py)
  R     runs/swarm-round3-hard17-v1-r.cases.jsonl + runs/swarm-round3-hard17-v1-r/arm_accounting.json
        (tail_replay --mode recall --output runs/swarm-round3-hard17-v1-r.jsonl via inkling/account_cmd.py)
  screens .runtime/closer_screen, .runtime/recall_screen (inkling/round3_gate.py screen)
Resume segments are merged with the frozen resume rule (run_variants.arm_latest). Server tokens are the
sglang:generation_tokens_total deltas of each segment's arm_accounting.json (summed over segments).

Mechanism (L plan): for winners whose accepted plan leaves a number unused (fewer than n-1 moves), the completion
tokens generated after the first thinking line on which a statement `expr = target` is detected (closers.line_statements;
the task restatement 'Target T' is not a statement). Tokens before that point inside the request are estimated in
proportion to characters (thinking + answer text of that request); later requests count in full.

usage: report_round3_hard17.py [--root DIR] [--out DIR] [--d DIR] [--l DIR] [--x DIR] [--c DIR] [--r-cases FILE]
                               [--r-accounting DIR] [--closer-screen PATH] [--recall-screen PATH]
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import closers  # noqa: E402
import round3_gate  # noqa: E402
import run_variants  # noqa: E402

STUDY = 'swarm-round3-hard17-v1'
DEFAULTS = dict(d=f'runs/{STUDY}-d-roll12strategy', l=f'runs/{STUDY}-l-roll12strategy', x=f'runs/{STUDY}-x-esc_extra',
                c=f'runs/{STUDY}-c', r_cases=f'runs/{STUDY}-r.cases.jsonl', r_accounting=f'runs/{STUDY}-r',
                closer_screen='.runtime/closer_screen', recall_screen='.runtime/recall_screen')
PLANS = {k: f'SWARM_ROUND3_HARD17_{k}_PLAN.json' for k in 'DLXCR'}
ADDON_RESCUES, ADDON_SHARE, NOISE = 2, 0.10, 2


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n)


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def accounting(dirs):
    """Server generation tokens, wall and Wh summed over the arm_accounting.json files of the given directories."""
    found = [json.loads((Path(d) / 'arm_accounting.json').read_text()) for d in dirs if (Path(d) / 'arm_accounting.json').exists()]
    if not found:
        return dict(server_tokens=None, wall_seconds=None, wh=None, segments_with_accounting=0, accounting_complete=False)
    tokens = [((a.get('server') or {}).get('total') or {}).get('generation_tokens') for a in found]
    whs = [(a.get('energy') or {}).get('total_wh') if isinstance(a.get('energy'), dict) else None for a in found]
    return dict(server_tokens=sum(t for t in tokens if t is not None), wall_seconds=round(sum(a.get('runner_wall_seconds') or 0 for a in found), 1),
                wh=round(sum(w for w in whs if w is not None), 2), segments_with_accounting=len(found),
                accounting_complete=len(found) == len(dirs) and None not in tokens and None not in whs
                and not any(a.get('accounting_error') or a.get('energy_error') for a in found))


def load_arm(path, root, policy):
    path = Path(path) if Path(path).is_absolute() else root / path
    if not (path / 'cases.jsonl').exists():
        return dict(status='not run', dir=str(path))
    try:
        arm = run_variants.arm_latest(path, root, policy=policy)
    except Exception as exc:  # mid-run: segments do not cover the plan's cases yet
        return dict(status='incomplete', dir=str(path), reason=str(exc)[:300])
    rows = {k: row for k, (_, row) in arm['latest'].items() if k in arm['clean']}
    acct = accounting(arm['segments'])
    return dict(status='complete' if not arm['unresolved'] else 'unresolved infra', dir=str(path), arm=arm, rows=rows,
                segments=[s.name for s in arm['segments']], superseded=arm['superseded'], unresolved=arm['unresolved'],
                tasks={t['id']: t for t in arm['tasks']}, **acct)


def arm_summary(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reason') if k in a}
    rows = list(a['rows'].values())
    n, solved, wrong = len(rows), sum(bool(r['solved']) for r in rows), sum(bool(r['wrong']) for r in rows)
    tok = a['server_tokens']
    return dict(status=a['status'], segments=a['segments'], cases=n, solved=solved, wrong=wrong,
                abstain=sum(not r['answered'] for r in rows), unresolved=len(a['unresolved']), server_tokens=tok,
                server_tokens_per_case=round(tok / n) if tok is not None and n else None,
                server_tokens_per_solved=round(tok / solved) if tok is not None and solved else None,
                wall_seconds=a['wall_seconds'], wh=a['wh'], accounting_complete=a['accounting_complete'])


def tokens_after_target(trace, target):
    """Completion tokens after the first thinking line with a detected statement whose value is the target, or None."""
    ends = [json.loads(line) for line in Path(trace).read_text().splitlines() if line.strip()]
    ends = [e for e in ends if e.get('type') == 'request_end']

    def tokens(e):
        return (e.get('usage') or {}).get('completion_tokens') or e.get('completion_tokens_charged') or len(e.get('token_ids') or [])
    for i, e in enumerate(ends):
        text = e.get('reasoning') or ''
        pos = 0
        for line in text.splitlines(keepends=True):
            pos += len(line)
            if any(st['value'] == target for st in closers.line_statements(line)):
                chars = len(text) + len(e.get('response') or '')
                after = tokens(e) * (1 - pos / chars) if chars else 0
                return round(after + sum(tokens(x) for x in ends[i + 1:]))
    return None


def mechanism(a, policy):
    if 'rows' not in a:
        return None
    values, never = [], 0
    for (task_id, seed), row in a['rows'].items():
        if not row.get('solved') or row.get('selected_slot') is None:
            continue
        agent = next((x for x in row['agents'] if x['slot'] == row['selected_slot']), None)
        task = a['tasks'][task_id]
        if not agent or not agent.get('plan') or len(agent['plan']['moves']) >= len(task['numbers']) - 1:
            continue  # all numbers used
        seg = a['arm']['latest'][(task_id, seed)][0]
        trace = seg / 'agents' / f"{task_id}-s{seed}-{policy}-a{agent['slot']}.jsonl"
        after = tokens_after_target(trace, task['target']) if trace.exists() else None
        if after is None:
            never += 1
        else:
            values.append(after)
    return dict(leftover_winners=len(values) + never, measured=len(values), target_statement_not_found=never,
                median=median(values), p90=pct(values, .9))


def addon_rescues(kind, root, paths):
    """{(task, seed): dict(rescued, wrong, slot)} of an add-on, plus status and accounting."""
    if kind == 'X':
        a = load_arm(paths['x'], root, 'esc_extra')
        if 'rows' not in a:
            return a
        cases = {k: dict(rescued=bool(r['solved']), wrong=bool(r['wrong']), slot=r.get('selected_slot'))
                 for k, r in a['rows'].items()}
        return dict(status=a['status'], cases=cases, unresolved=len(a['unresolved']), **{k: a[k] for k in (
            'server_tokens', 'wall_seconds', 'wh', 'accounting_complete')})
    if kind == 'C':
        d = root / paths['c']
        if not (d / 'cases.jsonl').exists():
            return dict(status='not run', dir=str(d))
        rows = round3_gate.read_rows(d / 'cases.jsonl')
        cases = {(r['task_id'], r['seed']): dict(rescued=bool(r['solved']), wrong=bool(r['wrong']), slot=r.get('selected_slot'),
                                                 infra=bool(r.get('infra'))) for r in rows}
        return dict(status='complete', cases=cases, unresolved=sum(c['infra'] for c in cases.values()), **accounting([d]))
    f = root / paths['r_cases']
    if not f.exists():
        return dict(status='not run', dir=str(f))
    cases = {}
    for r in round3_gate.read_rows(f):
        _, rescued, wrong, fault = round3_gate.case_outcome(r)
        if rescued is not None:
            cases[(r['task_id'], r['seed'])] = dict(rescued=rescued, wrong=wrong, slot=None, infra=fault)
    return dict(status='complete', cases=cases, unresolved=sum(c['infra'] for c in cases.values()),
                **accounting([root / paths['r_accounting']]))


def addon_summary(name, x, d_abst, d_tokens):
    if 'cases' not in x:
        return {k: x[k] for k in ('status', 'dir', 'reason') if k in x}
    rescued = sorted(k for k, c in x['cases'].items() if c['rescued'] and k in d_abst)
    wrong = sorted(k for k, c in x['cases'].items() if c['wrong'])
    tok = x['server_tokens']
    share = round(tok / d_tokens, 4) if tok is not None and d_tokens else None
    out = dict(status=x['status'], cases=len(x['cases']), d_abstentions=len(d_abst),
               outside_d_abstentions=len(set(x['cases']) - d_abst), rescued=len(rescued), wrong=len(wrong),
               unresolved=x['unresolved'], server_tokens=tok, share_of_d_tokens=share, wall_seconds=x.get('wall_seconds'),
               wh=x.get('wh'), accounting_complete=x.get('accounting_complete'),
               rescued_cases=[list(k) for k in rescued], wrong_cases=[list(k) for k in wrong])
    if name == 'X':
        out['rescue_slots'] = sorted(x['cases'][k]['slot'] for k in rescued)
    return out


def decisions(s):
    D, L = s['arms']['D'], s['arms']['L']
    X, C, R = (s['addons'][k] for k in 'XCR')
    out = {}
    if 'solved' in D and 'solved' in L:
        cheaper = (L['server_tokens_per_solved'] is not None and D['server_tokens_per_solved'] is not None
                   and L['server_tokens_per_solved'] < D['server_tokens_per_solved'])
        rule = dict(zero_wrong=L['wrong'] == 0, solved_within_noise=L['solved'] >= D['solved'] - NOISE,
                    cheaper_per_solved=cheaper)
        rule['adopt_sentence'] = all(rule.values())
        rule['rejected_pending_review'] = L['solved'] <= D['solved'] - NOISE - 1
        out['L'] = rule
    else:
        out['L'] = 'not evaluable (D or L not complete)'
    if 'rescued' in X:
        ok = X['rescued'] >= ADDON_RESCUES and X['wrong'] == 0
        cap = ('cap 16' if all(slot is not None and slot <= 15 for slot in X['rescue_slots']) else 'cap 20') if ok else 'no change'
        out['X'] = dict(rescued_at_least_2=X['rescued'] >= ADDON_RESCUES, zero_wrong=X['wrong'] == 0, outcome=cap)
    else:
        out['X'] = 'not evaluable (X not run)'
    for name, a in (('C', C), ('R', R)):
        if 'rescued' in a:
            rule = dict(zero_wrong=a['wrong'] == 0, rescued_at_least_2=a['rescued'] >= ADDON_RESCUES,
                        tokens_at_most_10pct_of_d=a['share_of_d_tokens'] is not None and a['share_of_d_tokens'] <= ADDON_SHARE)
            rule['adopt'] = all(rule.values())
            out[name] = rule
        else:
            out[name] = f'not evaluable ({name} not run)'
    passing = [n for n in ('C', 'R') if isinstance(out[n], dict) and out[n]['adopt']]
    if len(passing) == 2:
        first = sorted(passing, key=lambda n: (-s['addons'][n]['rescued'], s['addons'][n]['server_tokens'] or 0))[0]
        out['C_and_R'] = f'both pass: adopt {first} first, re-test the other on top'
    return out


def overlap(addons):
    sets = {k: {tuple(c) for c in a['rescued_cases']} for k, a in addons.items() if 'rescued_cases' in a}
    pairs = {f'{a}&{b}': len(sets[a] & sets[b]) for a in sets for b in sets if a < b}
    return dict(rescued=dict((k, len(v)) for k, v in sets.items()), pairwise=pairs,
                all=len(set.intersection(*sets.values())) if sets else 0, union=len(set().union(*sets.values())) if sets else 0)


def disclosure():
    doc = (HERE / 'account_cmd.py').read_text()
    m = re.search(r'Weaknesses that remain.*?(?=\n\n)', doc, re.S)
    return ' '.join(m.group().split()) if m else 'see inkling/account_cmd.py'


def build(root, paths):
    D = load_arm(paths['d'], root, 'roll12strategy')
    L = load_arm(paths['l'], root, 'roll12strategy')
    s = dict(study=STUDY, arms=dict(D=arm_summary(D), L=arm_summary(L)))
    if 'rows' in D and 'rows' in L:
        common = sorted(set(D['rows']) & set(L['rows']))
        wins = sum(bool(L['rows'][k]['solved']) and not D['rows'][k]['solved'] for k in common)
        losses = sum(bool(D['rows'][k]['solved']) and not L['rows'][k]['solved'] for k in common)
        s['paired_L_vs_D'] = dict(cases=len(common), l_only=wins, d_only=losses, sign_test_p=round(sign_test(wins, losses), 4))
    s['mechanism'] = dict(D=mechanism(D, 'roll12strategy'), L=mechanism(L, 'roll12strategy'))
    d_abst = {k for k, r in D.get('rows', {}).items() if not r['answered']}
    d_tokens = s['arms']['D'].get('server_tokens')
    s['addons'] = {k: addon_summary(k, addon_rescues(k, root, paths), d_abst, d_tokens) for k in 'XCR'}
    s['overlap'] = overlap(s['addons'])
    s['screens'] = {}
    for name, key in (('closer', 'closer_screen'), ('recall', 'recall_screen')):
        p = root / paths[key]
        try:
            s['screens'][name] = round3_gate.screen(p) if p.exists() else 'not run'
        except (SystemExit, ValueError) as exc:
            s['screens'][name] = f'unreadable: {exc}'
    s['decisions'] = decisions(s)
    s['plans'] = {k: (json.loads((root / f).read_text()).get('decision_rule') or json.loads((root / f).read_text()).get('gate'))
                  if (root / f).exists() else 'plan not written' for k, f in PLANS.items()}
    s['disclosure'] = disclosure()
    return s


def fmt(v):
    if v is None:
        return '-'
    if isinstance(v, float):
        return f'{v:,.4g}' if abs(v) < 10 else f'{v:,.1f}'
    if isinstance(v, int):
        return f'{v:,}'
    return str(v)


def markdown(s):
    out = [f'# {STUDY}', '', '## D vs L', '',
           '| arm | status | cases | solved | wrong | abstain | server tokens/case | tokens/solved | wall s | Wh |',
           '|---|---|---|---|---|---|---|---|---|---|']
    for k in 'DL':
        a = s['arms'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong', 'abstain', 'server_tokens_per_case', 'server_tokens_per_solved', 'wall_seconds', 'wh')) + ' |')
    if 'paired_L_vs_D' in s:
        p = s['paired_L_vs_D']
        out += ['', f"Paired: L-only solved {p['l_only']}, D-only {p['d_only']}, exact sign test p = {p['sign_test_p']}."]
    out += ['', '### Mechanism: tokens after the target first appears (winners that leave a number unused)', '',
            '| arm | leftover winners | measured | median | p90 |', '|---|---|---|---|---|']
    for k in 'DL':
        m = s['mechanism'][k]
        out.append(f'| {k} | not run | - | - | - |' if m is None else
                   f"| {k} | {m['leftover_winners']} | {m['measured']} | {fmt(m['median'])} | {fmt(m['p90'])} |")
    out += ['', "## Add-ons on D's clean abstentions", '',
            "| add-on | status | cases | rescued | wrong | server tokens | share of D | Wh |", '|---|---|---|---|---|---|---|---|']
    for k in 'XCR':
        a = s['addons'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'rescued', 'wrong', 'server_tokens', 'share_of_d_tokens', 'wh')) + ' |')
    o = s['overlap']
    out += ['', f"Rescued overlap: {o['pairwise']}; in all: {o['all']}; union: {o['union']}.", '', '## Screens', '']
    for name, g in s['screens'].items():
        out.append(f'- {name}: ' + (g if isinstance(g, str) else
                                     f"{g['rescued']} rescued, {g['wrong']} wrong of {g['cases']} -> {'PASS' if g['pass'] else 'FAIL'}"))
    out += ['', '## Decision rules', '']
    for k, v in s['decisions'].items():
        out.append(f'- {k}: {json.dumps(v)}')
    out += ['', '### Frozen rules (plans)', '']
    for k, v in s['plans'].items():
        out.append(f'- {k}: {v}')
    out += ['', '## Accounting disclosure', '', s['disclosure'], '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path)
    for key, value in DEFAULTS.items():
        p.add_argument('--' + key.replace('_', '-'), default=value)
    a = p.parse_args(argv)
    root = a.root.resolve()
    paths = {k: getattr(a, k) for k in DEFAULTS}
    s = build(root, paths)
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), D=s['arms']['D']['status'], L=s['arms']['L']['status'],
                          addons={k: v['status'] for k, v in s['addons'].items()})))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
