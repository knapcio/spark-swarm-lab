#!/usr/bin/env python3
"""Report for study coding-reserve-v1: the elastic answer reserve (IDEAS-swarm-round5-fable idea 1) in the coding swarm.
  P = R2 (run_coding_earlystop.py, rolling width 2) with the plain agent code_xl        plan CODING_RESERVE_P_PLAN.json
  A = R2 with every agent on the reserve variant the replay screen chose (code_reserve = N, budget-neutral: thinking
      26,624 within 32,768; or code_elastic = E: thinking 30,720, up to 8,192 extra answer tokens, 40,960 per agent)
                                                                                         plan CODING_RESERVE_A_PLAN.json
Runs runs/coding-reserve-v1-{p,a} on fresh seeds, each arm alone via inkling/coding_arms.py. Writes
results/coding-reserve-v1/{REPORT.md, report.json}.

Validation and pairing are report_aot_coding's (embedded frozen plan, R2 runner, one variant per arm, clean
completion, no operational fault under the runner's own rule, exact case set, accounting, Wh, no retry events; both
plans equal in agent count, matrix, seeds, offsets, rolling width and the other compute fields; the same non-empty
case set). Decision (Fable, complete inputs only, unrounded): the reserve is adopted if A unanswered <= P unanswered,
A solved >= P solved - 1, A wrong <= P wrong + 1 and A server generation tokens <= 1.00 x P; otherwise not. Reported
with it: arm wall, cut-off answers per arm (an agent whose final answer still ended by length), and the path of every
wrong answer (the winner's own end: self-closed answer, forced answer or continued answer, with its answer steps).

usage: report_reserve_coding.py [--root DIR] [--out DIR] [--p DIR] [--a DIR] [--p-plan FILE] [--a-plan FILE]
                                [--variant code_reserve|code_elastic]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_aot_coding as rac  # noqa: E402  (validation, summary and pairing)
import report_round3_hard17 as r3  # noqa: E402

STUDY = 'coding-reserve-v1'
ARMS = dict(P=dict(plan='CODING_RESERVE_P_PLAN.json', dir=f'runs/{STUDY}-p', variant='code_xl'),
            A=dict(plan='CODING_RESERVE_A_PLAN.json', dir=f'runs/{STUDY}-a', variant='code_reserve'))
RESERVE_VARIANTS = ('code_reserve', 'code_elastic')


def trace_end(a, row):
    path = Path(a['dir']) / Path(str(row.get('events') or '')).name
    end = {}
    if path.is_file():
        for e in rac.events(path):
            if e.get('type') == 'puzzle_end':
                end = e
    return end


def answer_path(end):
    """How an agent's answer came about, from its puzzle_end (both code_xl and the reserve variants)."""
    if end.get('budget_forced'):
        kind = 'forced'
    elif end.get('answer_continued'):
        kind = 'continued'
    else:
        kind = 'self_closed'
    steps = end.get('answer_steps', 1 if kind != 'self_closed' else 0)
    cut = end.get('answer_cut')
    if cut is None:  # code_xl: the forced/continued answer's finish, or a first call cut after closing thinking
        cut = (end.get('forced_finish_reason') == 'length' if kind != 'self_closed'
               else end.get('first_finish_reason') == 'length')
    return dict(path=kind, answer_steps=steps, answer_cut=bool(cut))


def answers(a):
    """Per-arm answer paths: cut-off answers among finished agents, and the path of every wrong winner."""
    stats, wrong = Counter(), []
    winners = {(k[0], k[1], c['winner_agent']): k for k, c in a['cases'].items() if c['answered']}
    for r in a['summary_rows']:
        if r.get('cancelled'):
            continue
        end = trace_end(a, r)
        if not end:
            stats['no_puzzle_end'] += 1
            continue
        p = answer_path(end)
        stats['finished'] += 1
        stats[p['path']] += 1
        stats['answer_cut'] += p['answer_cut']
        stats['answer_cut_failed'] += p['answer_cut'] and not r.get('feedback_pass')
        key = winners.get((r.get('task_id'), r.get('seed'), r.get('agent')))
        if key is not None and a['cases'][key]['wrong']:
            wrong.append(dict(task_id=key[0], seed=key[1], agent=r.get('agent'), **p))
    return dict(stats), wrong


def decision(arms, pairing_problems):
    P, A = arms['P'], arms['A']
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in arms.items() if a.get('status') != 'complete']
    why += [f'pairing: {p}' for p in pairing_problems]
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(unanswered_at_most_plain=A['unanswered'] <= P['unanswered'], solved_at_least_plain_minus_1=A['solved'] >= P['solved'] - 1,
                wrong_at_most_plain_plus_1=A['wrong'] <= P['wrong'] + 1,
                tokens_at_most_100pct=A['generated_tokens'] <= P['generated_tokens'])
    rule['reserve_adopted'] = all(rule.values())
    return rule


def build(root, dirs, plans=None, variant='code_reserve'):
    if variant not in RESERVE_VARIANTS:
        raise ValueError(f'variant must be one of {RESERVE_VARIANTS}')
    plans = plans or {k: v['plan'] for k, v in ARMS.items()}
    variants = dict(P='code_xl', A=variant)
    loaded = {k: rac.load(root, dirs[k], plans[k], variants[k]) for k in ARMS}
    s = dict(study=STUDY, variant=variant, arms={k: rac.summarize(a) for k, a in loaded.items()})
    s['pairing_problems'] = rac.pairing(loaded)
    P, A = loaded['P'], loaded['A']
    if 'cases' in P and 'cases' in A:
        common = sorted(set(P['cases']) & set(A['cases']))
        wins = sum(A['cases'][k]['solved'] and not P['cases'][k]['solved'] for k in common)
        losses = sum(P['cases'][k]['solved'] and not A['cases'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), reserve_only=wins, plain_only=losses, sign_test_p=r3.sign_test(wins, losses))
    for k, a in loaded.items():
        if 'cases' in a:
            s['arms'][k]['answers'], s['arms'][k]['wrong_paths'] = answers(a)
    s['decision'] = decision(s['arms'], s['pairing_problems'])
    s['frozen_rules'] = {k: (a.get('plan') or {}).get('decision_rule', 'plan not written') for k, a in loaded.items()}
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}: elastic answer reserve in the coding swarm (R2, {s["variant"]})', '',
           '| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | '
           'cut-off answers |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong', 'unanswered', 'generated_tokens', 'generated_tokens_per_case', 'wall_seconds',
            'wh', 'wh_per_solved')) + f" | {fmt((a.get('answers') or {}).get('answer_cut'))} |")
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if s['pairing_problems']:
        out += ['', f"Pairing incomplete: {'; '.join(s['pairing_problems'])}"]
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired ({p['cases']} cases): reserve-only solved {p['reserve_only']}, plain-only {p['plain_only']}, "
                    f"exact sign test p = {p['sign_test_p']:.4g}."]
    for k in ARMS:
        if 'answers' in s['arms'][k]:
            out += ['', f"{k} answer paths: {json.dumps(s['arms'][k]['answers'])}",
                    f"{k} wrong answers: {json.dumps(s['arms'][k]['wrong_paths']) if s['arms'][k]['wrong_paths'] else 'none'}"]
    out += ['', '## Decision (complete inputs, unrounded values)', '', f"Rules: {json.dumps(s['frozen_rules'])}", '',
            f"Evaluation: {json.dumps(s['decision'])}", '', '## Disclosures', '',
            'The reserve is one transport rule on finish_reason (no task content, no prompt change): an answer cut by '
            'length is continued in the same sequence in 2,048-token steps, at most 10,240 answer tokens, every step '
            'charged and reported. ' + ('code_reserve keeps the 32,768-token agent budget (thinking cap 26,624).'
                                        if s['variant'] == 'code_reserve' else
                                        'code_elastic gives an agent up to 8,192 more tokens than the frozen 32,768 '
                                        '(40,960; answer phase only); any comparison against other systems must state it.'),
            'Neither worker has a transport retry. Acceptance is the public feedback cases; the hidden holdout cases only '
            'score. Tokens are server counters over each arm\'s window. Idea: IDEAS-swarm-round5-fable.md, idea 1.', '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path)
    p.add_argument('--variant', choices=RESERVE_VARIANTS, default='code_reserve')
    for k, v in ARMS.items():
        p.add_argument('--' + k.lower(), default=v['dir'])
        p.add_argument(f'--{k.lower()}-plan', default=v['plan'])
    a = p.parse_args(argv)
    root = a.root.resolve()
    s = build(root, {k: getattr(a, k.lower()) for k in ARMS}, {k: getattr(a, f'{k.lower()}_plan') for k in ARMS}, a.variant)
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), arms={k: v['status'] for k, v in s['arms'].items()},
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['reserve_adopted'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
