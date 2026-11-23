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

Mechanism (L plan; offline analysis only): for winners whose accepted plan leaves a number unused (fewer than n-1
moves), discovery = the first thinking line of the accepted plan's stream (the last error-free request and, for a
forced/continued answer, the request it continues; a transport-retried earlier attempt is not part of it) holding an
equation (closers.line_statements) that is arithmetically TRUE when evaluated exactly with Fraction and whose result
is the target. Tokens after discovery are counted only within that stream: the rest of the discovery request
(estimated in proportion to characters of its thinking + answer text) plus the continuation request in full.

Decisions use unrounded values and are made only for complete inputs: D, L and X need no unresolved infra case under
the frozen resume rule and a valid arm_accounting.json for every segment (token counter present, finite, no negative
per-node delta, idle after the window, no accounting error); C and R need their case file without faulted rows, a
valid account_cmd record (runner exit 0, no accounting or energy error) and a passing dev-screen gate; every add-on
decision also needs D complete. Anything else is 'incomplete' with the reason, never zero-filled.

usage: report_round3_hard17.py [--root DIR] [--out DIR] [--d DIR] [--l DIR] [--x DIR] [--c DIR] [--r-cases FILE]
                               [--r-accounting DIR] [--closer-screen PATH] [--recall-screen PATH]
"""
import argparse
import json
import math
import re
import sys
from fractions import Fraction
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


def accounting(dirs, wrapper=False):
    """Server generation tokens, wall and Wh summed over the arm_accounting.json of every directory, with validity:
    every directory has a record, its token counter is present and finite, no per-node delta is negative, the fleet
    was idle after the window and there is no accounting error; wrapper (account_cmd) records also need runner exit 0
    and no energy error. Invalid -> server_tokens None and the problems listed (never zero-filled)."""
    problems, tokens, wall, whs = [], 0, 0.0, []
    for d in dirs:
        f = Path(d) / 'arm_accounting.json'
        if not f.exists():
            problems.append(f'{Path(d).name}: no arm_accounting.json')
            continue
        a = json.loads(f.read_text())
        total = ((a.get('server') or {}).get('total') or {}).get('generation_tokens')
        per_node = ((a.get('server') or {}).get('per_node') or {})
        if not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0:
            problems.append(f'{Path(d).name}: generation_tokens missing or invalid')
        else:
            tokens += total
        if any(not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for n in per_node.values() for x in n.values()):
            problems.append(f'{Path(d).name}: negative or non-finite per-node delta')
        if a.get('idle_after') is False:
            problems.append(f'{Path(d).name}: fleet not idle after the window')
        if a.get('accounting_error'):
            problems.append(f"{Path(d).name}: {a['accounting_error'][:120]}")
        if wrapper and (a.get('runner_exit') != 0 or a.get('energy_error') or 'command' not in a):
            problems.append(f"{Path(d).name}: account_cmd record not clean (runner_exit {a.get('runner_exit')}, "
                            f"energy_error {a.get('energy_error')})")
        wall += a.get('runner_wall_seconds') or 0
        energy = a.get('energy') if isinstance(a.get('energy'), dict) else {}
        whs.append(energy.get('total_wh') if not energy.get('error') else None)
    return dict(server_tokens=None if problems or not dirs else tokens, wall_seconds=wall,
                wh=sum(whs) if whs and None not in whs else None, accounting_valid=not problems and bool(dirs),
                accounting_problems=problems)


def load_arm(path, root, policy):
    path = Path(path) if Path(path).is_absolute() else root / path
    if not (path / 'cases.jsonl').exists():
        return dict(status='not run', dir=str(path))
    try:
        arm = run_variants.arm_latest(path, root, policy=policy)
    except Exception as exc:  # mid-run: segments do not cover the plan's cases yet
        return dict(status='incomplete', dir=str(path), reasons=[str(exc)[:300]])
    rows = {k: row for k, (_, row) in arm['latest'].items() if k in arm['clean']}
    acct = accounting(arm['segments'])
    reasons = ([f"{len(arm['unresolved'])} unresolved infra case(s)"] if arm['unresolved'] else []) + acct['accounting_problems']
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, dir=str(path), arm=arm, rows=rows,
                segments=[s.name for s in arm['segments']], superseded=arm['superseded'], unresolved=arm['unresolved'],
                tasks={t['id']: t for t in arm['tasks']}, **acct)


def arm_summary(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
    rows = list(a['rows'].values())
    n, solved, wrong = len(rows), sum(bool(r['solved']) for r in rows), sum(bool(r['wrong']) for r in rows)
    tok = a['server_tokens']
    return dict(status=a['status'], reasons=a['reasons'], segments=a['segments'], cases=n, solved=solved, wrong=wrong,
                abstain=sum(not r['answered'] for r in rows), unresolved=len(a['unresolved']), server_tokens=tok,
                server_tokens_per_case=tok / n if tok is not None and n else None,
                server_tokens_per_solved=tok / solved if tok is not None and solved else None,
                wall_seconds=a['wall_seconds'], wh=a['wh'])


def evaluate(tokens):
    """Exact value of an expression of numbers, + - * / and parentheses (Fraction); None if malformed or /0.
    Offline analysis only (the mechanism measure); no runtime decision uses it."""
    pos = 0

    def atom():
        nonlocal pos
        if pos < len(tokens) and tokens[pos] == '(':
            pos += 1
            value = expr()
            if pos >= len(tokens) or tokens[pos] != ')':
                raise ValueError
            pos += 1
            return value
        if pos < len(tokens) and tokens[pos].isdigit():
            pos += 1
            return Fraction(int(tokens[pos - 1]))
        raise ValueError

    def term():
        nonlocal pos
        value = atom()
        while pos < len(tokens) and tokens[pos] in '*/':
            op = tokens[pos]
            pos += 1
            rhs = atom()
            value = value * rhs if op == '*' else value / rhs
        return value

    def expr():
        nonlocal pos
        value = term()
        while pos < len(tokens) and tokens[pos] in '+-':
            op = tokens[pos]
            pos += 1
            value = value + term() if op == '+' else value - term()
        return value
    try:
        value = expr()
    except (ValueError, ZeroDivisionError):
        return None
    return value if pos == len(tokens) else None


def accepted_stream(ends):
    """The request_end events of the stream that produced the answer: the last error-free request and, if it continues
    another request (parent_request_id), that request first."""
    last = next((e for e in reversed(ends) if not e.get('error')), None)
    if last is None:
        return []
    parent = next((e for e in ends if last.get('parent_request_id') and e.get('request_id') == last['parent_request_id']), None)
    return [parent, last] if parent else [last]


def tokens_after_target(trace, target):
    """Completion tokens after discovery (first TRUE equation with result = target) within the accepted stream."""
    ends = [json.loads(line) for line in Path(trace).read_text().splitlines() if line.strip()]
    stream = accepted_stream([e for e in ends if e.get('type') == 'request_end'])

    def tokens(e):
        return (e.get('usage') or {}).get('completion_tokens') or e.get('completion_tokens_charged') or len(e.get('token_ids') or [])
    for i, e in enumerate(stream):
        text = e.get('reasoning') or ''
        pos = 0
        for line in text.splitlines(keepends=True):
            pos += len(line)
            if any(st['value'] == target and evaluate(st['tokens']) == target for st in closers.line_statements(line)):
                chars = len(text) + len(e.get('response') or '')
                after = tokens(e) * (1 - pos / chars) if chars else 0
                return after + sum(tokens(x) for x in stream[i + 1:])
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


def addon_rescues(kind, root, paths, screens):
    """{(task, seed): dict(rescued, wrong, slot)} of an add-on, plus status (complete only when decidable)."""
    if kind == 'X':
        a = load_arm(paths['x'], root, 'esc_extra')
        if 'rows' not in a:
            return a
        cases = {k: dict(rescued=bool(r['solved']), wrong=bool(r['wrong']), slot=r.get('selected_slot'))
                 for k, r in a['rows'].items()}
        return dict(status=a['status'], reasons=a['reasons'], cases=cases, unresolved=len(a['unresolved']),
                    **{k: a[k] for k in ('server_tokens', 'wall_seconds', 'wh')})
    if kind == 'C':
        d = root / paths['c']
        if not (d / 'cases.jsonl').exists():
            return dict(status='not run', dir=str(d))
        cases = {(r['task_id'], r['seed']): dict(rescued=bool(r['solved']), wrong=bool(r['wrong']), slot=r.get('selected_slot'),
                                                 infra=bool(r.get('infra'))) for r in round3_gate.read_rows(d / 'cases.jsonl')}
        acct, screen = accounting([d], wrapper=True), screens.get('closer')
    else:
        f = root / paths['r_cases']
        if not f.exists():
            return dict(status='not run', dir=str(f))
        cases = {}
        for r in round3_gate.read_rows(f):
            _, rescued, wrong, fault = round3_gate.case_outcome(r)
            if rescued is not None:
                cases[(r['task_id'], r['seed'])] = dict(rescued=rescued, wrong=wrong, slot=None, infra=fault)
        acct, screen = accounting([root / paths['r_accounting']], wrapper=True), screens.get('recall')
    faulted = sum(c['infra'] for c in cases.values())
    reasons = ([f'{faulted} faulted case row(s)'] if faulted else []) + acct['accounting_problems']
    if not (isinstance(screen, dict) and screen.get('pass') is True):
        reasons.append(f'dev-screen gate not passed or not recorded: {screen if isinstance(screen, str) else "FAIL"}')
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, cases=cases, unresolved=faulted,
                **{k: acct[k] for k in ('server_tokens', 'wall_seconds', 'wh')})


def addon_summary(name, x, d_abst, d_tokens):
    if 'cases' not in x:
        return {k: x[k] for k in ('status', 'dir', 'reasons') if k in x}
    rescued = sorted(k for k, c in x['cases'].items() if c['rescued'] and k in d_abst)
    wrong = sorted(k for k, c in x['cases'].items() if c['wrong'])
    tok = x['server_tokens']
    share = tok / d_tokens if tok is not None and d_tokens else None
    out = dict(status=x['status'], reasons=x['reasons'], cases=len(x['cases']), d_abstentions=len(d_abst),
               outside_d_abstentions=len(set(x['cases']) - d_abst), rescued=len(rescued), wrong=len(wrong),
               unresolved=x['unresolved'], server_tokens=tok, share_of_d_tokens=share, wall_seconds=x.get('wall_seconds'),
               wh=x.get('wh'), rescued_cases=[list(k) for k in rescued], wrong_cases=[list(k) for k in wrong])
    if name == 'X':
        out['rescue_slots'] = sorted(x['cases'][k]['slot'] for k in rescued)
    return out


def decisions(s):
    """Each plan's frozen rule on unrounded values, only for complete inputs (else 'incomplete: reasons')."""
    D, L = s['arms']['D'], s['arms']['L']
    X, C, R = (s['addons'][k] for k in 'XCR')

    def blocked(name, *parts):
        why = [f"{n}: {p.get('status')}" + (f" ({'; '.join(p.get('reasons') or [])})" if p.get('reasons') else '')
               for n, p in parts if p.get('status') != 'complete']
        return f"incomplete - {' | '.join(why)}" if why else None
    out = {}
    out['L'] = blocked('L', ('D', D), ('L', L))
    if out['L'] is None:
        cheaper = (L['server_tokens_per_solved'] is not None and D['server_tokens_per_solved'] is not None
                   and L['server_tokens_per_solved'] < D['server_tokens_per_solved'])
        rule = dict(zero_wrong=L['wrong'] == 0, solved_within_noise=L['solved'] >= D['solved'] - NOISE,
                    cheaper_per_solved=cheaper)
        rule['adopt_sentence'] = all(rule.values())
        rule['rejected_pending_review'] = L['solved'] <= D['solved'] - NOISE - 1
        out['L'] = rule
    out['X'] = blocked('X', ('D', D), ('X', X))
    if out['X'] is None:
        ok = X['rescued'] >= ADDON_RESCUES and X['wrong'] == 0
        cap = ('cap 16' if all(slot is not None and slot <= 15 for slot in X['rescue_slots']) else 'cap 20') if ok else 'no change'
        out['X'] = dict(rescued_at_least_2=X['rescued'] >= ADDON_RESCUES, zero_wrong=X['wrong'] == 0, outcome=cap)
    for name, a in (('C', C), ('R', R)):
        out[name] = blocked(name, ('D', D), (name, a))
        if out[name] is None:
            rule = dict(zero_wrong=a['wrong'] == 0, rescued_at_least_2=a['rescued'] >= ADDON_RESCUES,
                        tokens_at_most_10pct_of_d=a['share_of_d_tokens'] is not None and a['share_of_d_tokens'] <= ADDON_SHARE)
            rule['adopt'] = all(rule.values())
            out[name] = rule
    passing = [n for n in ('C', 'R') if isinstance(out[n], dict) and out[n]['adopt']]
    if len(passing) == 2:
        first = sorted(passing, key=lambda n: (-s['addons'][n]['rescued'], s['addons'][n]['server_tokens']))[0]
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
    s['screens'] = {}
    for name, key in (('closer', 'closer_screen'), ('recall', 'recall_screen')):
        p = root / paths[key]
        try:
            s['screens'][name] = round3_gate.screen(p) if p.exists() else 'not run'
        except (SystemExit, ValueError) as exc:
            s['screens'][name] = f'unreadable: {exc}'
    s['addons'] = {k: addon_summary(k, addon_rescues(k, root, paths, s['screens']), d_abst, d_tokens) for k in 'XCR'}
    s['overlap'] = overlap(s['addons'])
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
    for k in 'DL':
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if 'paired_L_vs_D' in s:
        p = s['paired_L_vs_D']
        out += ['', f"Paired: L-only solved {p['l_only']}, D-only {p['d_only']}, exact sign test p = {p['sign_test_p']}."]
    out += ['', '### Mechanism: tokens after discovery (winners that leave a number unused)', '',
            'Discovery = the first thinking line of the accepted plan\'s stream with an arithmetically true equation '
            '(exact Fraction evaluation, offline analysis only) whose result is the target; tokens after it are counted '
            'only within that stream (rest of the discovery request, estimated by characters, plus its continuation).', '',
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
    for k in 'XCR':
        if s['addons'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['addons'][k]['reasons'])}")
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
