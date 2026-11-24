#!/usr/bin/env python3
"""Report for study swarm-split-hard18-v1 (SWARM_SPLIT_HARD18_PLAN.json): roll12strategy (default, STRATEGIES hints for
escalation agents) vs roll12split (last-move partition hints SPLIT_HINTS) on arithmetic-hard-v18.
Writes results/swarm-split-hard18-v1/{REPORT.md, report.json}. Works mid-study: an arm without output is 'not run',
an arm whose segments do not yet cover its cases or whose accounting is invalid is 'incomplete' (no decision).

Inputs: runs/swarm-split-hard18-v1-<policy>[-resumeN] (run_variants via inkling/arms.py, one arm at a time).
Resume segments are merged with the frozen resume rule (run_variants.arm_latest); cost totals include the accounting
of every segment directory present, validated as in report_round3_hard17 (counter present and finite, no negative or
zero-with-activity per-node delta, idle after the window, no accounting error): invalid -> 'incomplete', never
zero-filled. Decisions use unrounded values.

Validity also needs every segment's embedded plan equal to the frozen plan file SWARM_SPLIT_HARD18_PLAN.json (its
sha256 is reported). A wrong answer in ANY attempt, including an infra-faulted attempt superseded by a resume, counts
against the zero-wrong criterion; such attempts are listed. Wasted work: each segment's own totals with the cases a
later segment superseded.

Mechanism: cases answered by an escalation agent (selected_slot >= 4) per arm, and judge-accepted escalation agents per
hint position (slot - 4) % 4 (with how many of them the exact verifier scores correct; scoring only).

usage: report_split_hard18.py [--root DIR] [--out DIR] [--strategy DIR] [--split DIR]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402  (arm loading, accounting validity, sign test, disclosure)

STUDY = 'swarm-split-hard18-v1'
PLAN = 'SWARM_SPLIT_HARD18_PLAN.json'
ARMS = ('roll12strategy', 'roll12split')
FIRST_ESCALATION_SLOT = 4
DESIGN_DISCLOSURE = ('Design notes: (1) an escalation agent runs on the node of the agent whose end freed its slot (as in '
                     'the default policy), so the same slot can run on different nodes in the two arms; (2) the sampling '
                     'seed of each request hashes the agent seed, stage and prompt token ids, so the two arms sample '
                     'differently for escalation agents (their prompts differ by the hint) even with equal agent seeds; '
                     '(3) the code_sha256 pins in the plan are records checked by review, not enforced by the runner '
                     '(it enforces only the worker source revision); arms.py must be given --source .runtime/xl-night-source.')


def summarize(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
    rows = list(a['rows'].values())
    n, solved, wrong = len(rows), sum(bool(r['solved']) for r in rows), sum(bool(r['wrong']) for r in rows)
    tok, wh = a['server_tokens'], a['wh']
    esc_answered = [r for r in rows if r['answered'] and (r.get('selected_slot') or 0) >= FIRST_ESCALATION_SLOT]
    positions = {p: dict(accepted=0, correct=0) for p in range(4)}
    for r in rows:
        for agent in r['agents']:
            if agent['slot'] >= FIRST_ESCALATION_SLOT and agent.get('verdict') is True:
                pos = positions[(agent['slot'] - FIRST_ESCALATION_SLOT) % 4]
                pos['accepted'] += 1
                pos['correct'] += bool(agent.get('verifier_solved'))
    return dict(status=a['status'], reasons=a['reasons'], segments=a['segments'], cases=n, solved=solved, wrong=wrong,
                wrong_all_attempts=a['wrong_all_attempts'], wrong_attempts=a['wrong_attempts'], wasted_work=a['wasted_work'],
                segment_accounting=a['segment_accounting'], plan_sha256=a['plan_sha256'],
                abstain=sum(not r['answered'] for r in rows), unresolved=len(a['unresolved']), server_tokens=tok,
                server_tokens_per_case=tok / n if tok is not None and n else None, wall_seconds=a['wall_seconds'], wh=wh,
                wh_per_solved=wh / solved if wh is not None and solved else None,
                escalation_answered=len(esc_answered), escalation_solved=sum(bool(r['solved']) for r in esc_answered),
                escalation_wrong=sum(bool(r['wrong']) for r in esc_answered),
                escalated_cases=sum((r.get('escalated_agents') or 0) > 0 for r in rows),
                accepted_escalation_by_hint_position=positions)


def decision(s):
    A, B = (s['arms'][k] for k in ARMS)
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in s['arms'].items() if a.get('status') != 'complete']
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(zero_wrong=B['wrong_all_attempts'] == 0, solved_at_least_default=B['solved'] >= A['solved'],
                escalation_answers_at_least_default=B['escalation_answered'] >= A['escalation_answered'])
    rule['adopt_roll12split'] = all(rule.values())
    return rule


def build(root, dirs):
    arms = {k: r3.load_arm(dirs[k], root, k, PLAN) for k in ARMS}
    s = dict(study=STUDY, arms={k: summarize(a) for k, a in arms.items()})
    A, B = (arms[k] for k in ARMS)
    if 'rows' in A and 'rows' in B:
        common = sorted(set(A['rows']) & set(B['rows']))
        wins = sum(bool(B['rows'][k]['solved']) and not A['rows'][k]['solved'] for k in common)
        losses = sum(bool(A['rows'][k]['solved']) and not B['rows'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), split_only=wins, strategy_only=losses, sign_test_p=r3.sign_test(wins, losses))
    s['decision'] = decision(s)
    plan = root / PLAN
    s['frozen_rule'] = json.loads(plan.read_text()).get('decision_rule') if plan.exists() else 'plan not written'
    s['disclosure'] = r3.disclosure()
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}', '', '## roll12strategy vs roll12split', '',
           '| arm | status | cases | solved | wrong | abstain | server tokens/case | wall s | Wh | Wh/solved |',
           '|---|---|---|---|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong', 'abstain', 'server_tokens_per_case', 'wall_seconds', 'wh', 'wh_per_solved')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired: roll12split-only solved {p['split_only']}, roll12strategy-only {p['strategy_only']}, "
                    f"exact sign test p = {p['sign_test_p']:.4g}."]
    out += ['', '## Mechanism: answers through escalation agents (slot >= 4)', '',
            '| arm | escalated cases | answered by escalation | solved | wrong | accepted per hint position 0/1/2/3 (correct) |',
            '|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        if 'escalation_answered' not in a:
            out.append(f'| {k} | {a["status"]} | - | - | - | - |')
            continue
        pos = a['accepted_escalation_by_hint_position']
        cells = ' / '.join(f"{pos[p]['accepted']} ({pos[p]['correct']})" for p in range(4))
        out.append(f"| {k} | {a['escalated_cases']} | {a['escalation_answered']} | {a['escalation_solved']} | "
                   f"{a['escalation_wrong']} | {cells} |")
    out += ['', '## Decision (frozen rule, unrounded values)', '', f"Rule: {s['frozen_rule']}", '',
            f"Evaluation: {json.dumps(s['decision'])}", '']
    out += ['## Wrong answers over all attempts and wasted work', '']
    for k in ARMS:
        a = s['arms'][k]
        if 'wrong_attempts' not in a:
            continue
        out.append(f"- {k}: {a['wrong_all_attempts']} wrong attempt(s)" +
                   (f": {json.dumps(a['wrong_attempts'])}" if a['wrong_attempts'] else ''))
        for w in a['wasted_work']:
            out.append(f"  - wasted segment {w['dir']}: server tokens {fmt(w.get('server_tokens'))}, wall "
                       f"{fmt(w.get('wall_seconds'))} s, {fmt(w.get('wh'))} Wh; "
                       + ('no case rows' if w.get('no_case_rows') else f"superseded cases {w['superseded_cases']}")
                       + ('' if w.get('accounting') else ' (no accounting record)'))
    out += ['', '## Disclosures', '', s['disclosure'], '', DESIGN_DISCLOSURE, '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path)
    p.add_argument('--strategy', default=f'runs/{STUDY}-roll12strategy')
    p.add_argument('--split', default=f'runs/{STUDY}-roll12split')
    a = p.parse_args(argv)
    root = a.root.resolve()
    s = build(root, dict(roll12strategy=a.strategy, roll12split=a.split))
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), arms={k: v['status'] for k, v in s['arms'].items()},
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['adopt_roll12split'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
