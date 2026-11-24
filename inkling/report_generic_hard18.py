#!/usr/bin/env python3
"""Report for study swarm-generic-hard18-v1 (SWARM_GENERIC_HARD18_PLAN.json): generic swarm policies on
arithmetic-hard-v18, three arms run one at a time by inkling/arms.py:
  S  = roll12strategy (current default: STRATEGIES hints for escalation agents)
  G  = roll12cancel   (the same swarm with no task-specific text at all)
  GI = roll12idle     (G plus idle-capacity escalation: slots 12-19 only on nodes below the occupancy threshold)
Writes results/swarm-generic-hard18-v1/{REPORT.md, report.json}. Mid-study an arm is 'not run' or 'incomplete'.

Validation is shared with report_round3_hard17 (frozen resume rule, accounting validity for every segment directory,
every segment's embedded plan equal to the frozen plan file, wrong answers over ALL attempts, wasted work).
Decisions (complete inputs only, unrounded values):
  G replaces S  if G has 0 wrong (all attempts) and G solved >= S solved - 2;
  GI replaces G if GI has 0 wrong (all attempts), GI solved >= G solved, at least 1 case answered by a slot >= 12,
                and GI arm wall <= 1.10 x G arm wall.

usage: report_generic_hard18.py [--root DIR] [--out DIR] [--s DIR] [--g DIR] [--gi DIR]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402

STUDY = 'swarm-generic-hard18-v1'
PLAN = 'SWARM_GENERIC_HARD18_PLAN.json'
ARMS = dict(S='roll12strategy', G='roll12cancel', GI='roll12idle')
EXTRA_SLOT = 12
NOISE, WALL_LIMIT = 2, 1.10
DESIGN_DISCLOSURE = (
    'Design notes: (1) escalation agents run on the node of the agent whose end freed their slot, so the same slot can '
    'run on different nodes in different arms; (2) each request\'s sampling seed hashes the agent seed, stage and '
    'prompt token ids, so S (hinted prompts) and G/GI (no hints) sample differently for escalation agents even with '
    'equal agent seeds, while G and GI share slots 0-11 exactly in seeds and prompts; (3) GI\'s extra agents depend on '
    'node occupancy in the shared slots (agents + judges of all cases of the arm), i.e. on the arm\'s own load, never '
    'on elapsed time; (4) the plan\'s code_sha256 pins are records checked by review, not enforced by the runner; '
    'arms.py must be given --source for the worker revision.')


def summarize(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
    rows = list(a['rows'].values())
    n, solved, wrong = len(rows), sum(bool(r['solved']) for r in rows), sum(bool(r['wrong']) for r in rows)
    tok, wh = a['server_tokens'], a['wh']
    out = dict(status=a['status'], reasons=a['reasons'], segments=a['segments'], cases=n, solved=solved, wrong=wrong,
               wrong_all_attempts=a['wrong_all_attempts'], wrong_attempts=a['wrong_attempts'], wasted_work=a['wasted_work'],
               abstain=sum(not r['answered'] for r in rows), unresolved=len(a['unresolved']), server_tokens=tok,
               server_tokens_per_case=tok / n if tok is not None and n else None, wall_seconds=a['wall_seconds'], wh=wh,
               wh_per_solved=wh / solved if wh is not None and solved else None, plan_sha256=a['plan_sha256'])
    extra = [r for r in rows if any(x['slot'] >= EXTRA_SLOT for x in r['agents'])]
    if extra or any('extra_agents' in r for r in rows):
        per_case = [sum(x['slot'] >= EXTRA_SLOT and x.get('started', True) for x in r['agents']) for r in rows]
        occupancy = [x['idle_occupancy_at_start'] for r in rows for x in r['agents']
                     if x['slot'] >= EXTRA_SLOT and 'idle_occupancy_at_start' in x]
        by_extra = [r for r in rows if r['answered'] and (r.get('selected_slot') or 0) >= EXTRA_SLOT]
        out.update(idle_phase_cases=sum(bool(r.get('idle_phase')) for r in rows),
                   extra_agents_total=sum(per_case), extra_agents_per_case=per_case,
                   extra_agents_per_idle_case=[c for c, r in zip(per_case, rows) if r.get('idle_phase')],
                   answered_by_extra=len(by_extra), solved_by_extra=sum(bool(r['solved']) for r in by_extra),
                   wrong_by_extra=sum(bool(r['wrong']) for r in by_extra),
                   occupancy_at_start=dict(n=len(occupancy), median=r3.median(occupancy),
                                           max=max(occupancy) if occupancy else None,
                                           histogram={str(k): occupancy.count(k) for k in sorted(set(occupancy))}))
    return out


def paired(x, y):
    """Cases solved by x only and by y only (common clean cases), exact sign test."""
    common = sorted(set(x['rows']) & set(y['rows']))
    wins = sum(bool(x['rows'][k]['solved']) and not y['rows'][k]['solved'] for k in common)
    losses = sum(bool(y['rows'][k]['solved']) and not x['rows'][k]['solved'] for k in common)
    return dict(cases=len(common), first_only=wins, second_only=losses, sign_test_p=r3.sign_test(wins, losses))


def blocked(arms, *names):
    why = [f"{n}: {arms[n]['status']}" + (f" ({'; '.join(arms[n].get('reasons') or [])})" if arms[n].get('reasons') else '')
           for n in names if arms[n].get('status') != 'complete']
    return f"incomplete - {' | '.join(why)}" if why else None


def decisions(arms):
    S, G, GI = arms['S'], arms['G'], arms['GI']
    out = dict(G=blocked(arms, 'S', 'G'), GI=blocked(arms, 'G', 'GI'))
    if out['G'] is None:
        rule = dict(zero_wrong=G['wrong_all_attempts'] == 0, solved_within_noise=G['solved'] >= S['solved'] - NOISE)
        rule['G_replaces_S'] = all(rule.values())
        out['G'] = rule
    if out['GI'] is None:
        rule = dict(zero_wrong=GI['wrong_all_attempts'] == 0, solved_at_least_G=GI['solved'] >= G['solved'],
                    answered_by_extra_slot=GI.get('answered_by_extra', 0) >= 1,
                    wall_at_most_110pct_of_G=G['wall_seconds'] > 0 and GI['wall_seconds'] <= WALL_LIMIT * G['wall_seconds'])
        rule['GI_replaces_G'] = all(rule.values())
        out['GI'] = rule
    return out


def build(root, dirs):
    loaded = {k: r3.load_arm(dirs[k], root, ARMS[k], PLAN) for k in ARMS}
    s = dict(study=STUDY, policies=ARMS, arms={k: summarize(a) for k, a in loaded.items()})
    s['paired'] = {}
    for x, y in (('G', 'S'), ('GI', 'G')):
        if 'rows' in loaded[x] and 'rows' in loaded[y]:
            s['paired'][f'{x}_vs_{y}'] = paired(loaded[x], loaded[y])
    s['decisions'] = decisions(s['arms'])
    plan = root / PLAN
    s['frozen_rules'] = json.loads(plan.read_text()).get('decision_rule') if plan.exists() else 'plan not written'
    s['disclosure'] = r3.disclosure()
    s['design_disclosure'] = DESIGN_DISCLOSURE
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}', '', '| arm | policy | status | cases | solved | wrong (all attempts) | abstain | server tokens/case | '
           'wall s | Wh | Wh/solved |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for k, pol in ARMS.items():
        a = s['arms'][k]
        out.append(f"| {k} | {pol} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong_all_attempts', 'abstain', 'server_tokens_per_case', 'wall_seconds', 'wh',
            'wh_per_solved')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    out += ['', '## Paired exact sign tests', '']
    for name, p in s['paired'].items():
        x, y = name.split('_vs_')
        out.append(f"- {x} vs {y}: {x}-only solved {p['first_only']}, {y}-only {p['second_only']}, p = {p['sign_test_p']:.4g}")
    gi = s['arms']['GI']
    out += ['', '## GI idle-capacity escalation (slots 12-19)', '']
    if 'extra_agents_total' in gi:
        occ = gi['occupancy_at_start']
        out += [f"- cases reaching the idle phase: {gi['idle_phase_cases']}; extra agents started: {gi['extra_agents_total']} "
                f"(per idle case: {gi['extra_agents_per_idle_case']})",
                f"- cases answered by a slot >= 12: {gi['answered_by_extra']} (solved {gi['solved_by_extra']}, wrong "
                f"{gi['wrong_by_extra']})",
                f"- node occupancy when an extra agent started: n {occ['n']}, median {fmt(occ['median'])}, max "
                f"{fmt(occ['max'])}, histogram {occ['histogram']}"]
    else:
        out.append(f"- {gi['status']}")
    out += ['', '## Decisions (complete inputs, unrounded values)', '']
    for k, v in s['decisions'].items():
        out.append(f'- {k}: {json.dumps(v)}')
    out += ['', f"Frozen rules: {s['frozen_rules']}", '', '## Wrong answers over all attempts and wasted work', '']
    for k in ARMS:
        a = s['arms'][k]
        if 'wrong_attempts' not in a:
            continue
        out.append(f"- {k}: {a['wrong_all_attempts']} wrong attempt(s)" +
                   (f": {json.dumps(a['wrong_attempts'])}" if a['wrong_attempts'] else ''))
        for w in a['wasted_work']:
            out.append(f"  - wasted segment {w['dir']}: server tokens {fmt(w.get('server_tokens'))}, wall "
                       f"{fmt(w.get('wall_seconds'))} s, {fmt(w.get('wh'))} Wh; "
                       + ('no case rows' if w.get('no_case_rows') else f"superseded cases {w['superseded_cases']}"))
    out += ['', '## Disclosures', '', s['disclosure'], '', s['design_disclosure'], '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path)
    for k, pol in ARMS.items():
        p.add_argument('--' + k.lower(), default=f'runs/{STUDY}-{pol}')
    a = p.parse_args(argv)
    root = a.root.resolve()
    s = build(root, {k: getattr(a, k.lower()) for k in ARMS})
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), arms={k: v['status'] for k, v in s['arms'].items()},
                          decisions={k: v if isinstance(v, str) else v.get(f'{k}_replaces_{"S" if k == "G" else "G"}')
                                     for k, v in s['decisions'].items()})))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
