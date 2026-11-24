#!/usr/bin/env python3
"""Report for study swarm-relay-hard19-v1 (SWARM_RELAY_HARD19_PLAN.json): G = roll12cancel (generic default) vs
RL = roll12relay (escalation agents get the generic relay protocol + one failed agent's verbatim work) on a fresh
corpus, each arm run alone by inkling/arms.py. Writes results/swarm-relay-hard19-v1/{REPORT.md, report.json}.

Validation is shared with report_round3_hard17 (frozen resume rule, accounting validity for every segment directory,
embedded plan equal to the frozen plan file, wrong answers over ALL attempts, wasted work, unrounded UTC window).
Server work per arm: generated tokens AND input work (prompt tokens, computed prefill) summed over every segment's
arm_accounting.json; total compute = generated + computed prefill. A missing or invalid input counter, a node with
activity but 0 prompt/prefill tokens (arms.py writes unread counters as 0), or missing Wh -> incomplete.
Decision (complete inputs only, unrounded): RL replaces G if RL has 0 wrong answers over all attempts, RL solved >=
G solved, and RL answers at least as many cases through escalation agents (selected slot >= 4) as G.

usage: report_relay_swarm.py [--root DIR] [--out DIR] [--g DIR] [--rl DIR]
"""
import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402

STUDY = 'swarm-relay-hard19-v1'
PLAN = 'SWARM_RELAY_HARD19_PLAN.json'
ARMS = dict(G='roll12cancel', RL='roll12relay')
FIRST_ESCALATION_SLOT = 4
INPUT_KEYS = ('prompt_tokens', 'prefill_compute_tokens')
DESIGN_DISCLOSURE = (
    'Design notes: (1) G and RL share slots 0-3 exactly (seeds, nodes, prompts); escalation agents run on the node of '
    'the agent whose end freed their slot, so their nodes can differ between arms; (2) each request\'s sampling seed '
    'hashes the prompt, so RL\'s escalation agents (prompt + relayed work) sample differently from G\'s even with equal '
    'agent seeds; (3) the relayed work is chosen by seeded uniform sampling among the case\'s already failed agents, '
    'never by content; (4) the plan\'s code_sha256 pins are records checked by review, not enforced by the runner.')


def input_work(a):
    """Prompt and computed-prefill tokens summed over every segment directory of the arm (None + problem if invalid).
    arms.py writes a counter it could not read as 0, so a node that shows activity (requests or generated tokens > 0)
    with prompt_tokens or prefill_compute_tokens == 0 (or missing) is invalid accounting."""
    totals, problems = dict.fromkeys(INPUT_KEYS, 0), []
    for d in r3.segment_dirs(a['arm']['base']):
        f = Path(d) / 'arm_accounting.json'
        rec = json.loads(f.read_text()) if f.exists() else {}
        for node, x in sorted(((rec.get('server') or {}).get('per_node') or {}).items()):
            x = x or {}
            active = (x.get('requests') or 0) > 0 or (x.get('generation_tokens') or 0) > 0
            if active and any(not isinstance(x.get(k), (int, float)) or x.get(k) == 0 for k in INPUT_KEYS):
                problems.append(f'{Path(d).name}: node {node} shows activity but prompt/prefill tokens are 0 or missing '
                                '(an unread counter is written as 0 by arms.py)')
        total = ((rec.get('server') or {}).get('total') or {})
        for k in INPUT_KEYS:
            x = total.get(k)
            if not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
                problems.append(f'{Path(d).name}: server {k} missing or invalid')
            else:
                totals[k] += x
    return (dict.fromkeys(INPUT_KEYS) if problems else totals), problems


def load(path, root, policy):
    a = r3.load_arm(path, root, policy, PLAN)
    if 'arm' not in a:
        return a
    work, problems = input_work(a)
    if a.get('wh') is None:
        problems.append('GPU energy (Wh) missing for a segment')
    if problems:
        a = dict(a, status='incomplete', reasons=a['reasons'] + problems)
    return dict(a, input_work=work)


def summarize(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
    rows = list(a['rows'].values())
    n, solved, wrong = len(rows), sum(bool(r['solved']) for r in rows), sum(bool(r['wrong']) for r in rows)
    gen, wh, work = a['server_tokens'], a['wh'], a['input_work']
    compute = gen + work['prefill_compute_tokens'] if gen is not None and work['prefill_compute_tokens'] is not None else None
    per_case = lambda x: x / n if x is not None and n else None
    esc = [r for r in rows if r['answered'] and (r.get('selected_slot') or 0) >= FIRST_ESCALATION_SLOT]

    def winner(r):
        return next((x for x in r['agents'] if x['slot'] == r.get('selected_slot')), {})
    relayed = [r for r in esc if winner(r).get('relay_source_slot') is not None]
    return dict(status=a['status'], reasons=a['reasons'], segments=a['segments'], cases=n, solved=solved, wrong=wrong,
                wrong_all_attempts=a['wrong_all_attempts'], wrong_attempts=a['wrong_attempts'], wasted_work=a['wasted_work'],
                abstain=sum(not r['answered'] for r in rows), unresolved=len(a['unresolved']),
                generated_tokens=gen, prompt_tokens=work['prompt_tokens'], prefill_compute_tokens=work['prefill_compute_tokens'],
                total_compute_tokens=compute, generated_per_case=per_case(gen), prompt_per_case=per_case(work['prompt_tokens']),
                prefill_compute_per_case=per_case(work['prefill_compute_tokens']), total_compute_per_case=per_case(compute),
                wall_seconds=a['window_seconds'], wall_us=a['window_us'], wh=wh,
                wh_per_solved=wh / solved if wh is not None and solved else None,
                escalation_answered=len(esc), escalation_solved=sum(bool(r['solved']) for r in esc),
                relayed_answered=len(relayed), relayed_solved=sum(bool(r['solved']) for r in relayed),
                relayed_agents=sum(x.get('relay_source_slot') is not None and x.get('started', True)
                                   for r in rows for x in r['agents']),
                plan_sha256=a['plan_sha256'])


def decision(arms):
    G, RL = arms['G'], arms['RL']
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in arms.items() if a.get('status') != 'complete']
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(zero_wrong=RL['wrong_all_attempts'] == 0, solved_at_least_G=RL['solved'] >= G['solved'],
                escalation_answers_at_least_G=RL['escalation_answered'] >= G['escalation_answered'])
    rule['RL_replaces_G'] = all(rule.values())
    return rule


def build(root, dirs):
    loaded = {k: load(dirs[k], root, ARMS[k]) for k in ARMS}
    s = dict(study=STUDY, policies=ARMS, arms={k: summarize(a) for k, a in loaded.items()})
    G, RL = loaded['G'], loaded['RL']
    if 'rows' in G and 'rows' in RL:
        common = sorted(set(G['rows']) & set(RL['rows']))
        wins = sum(bool(RL['rows'][k]['solved']) and not G['rows'][k]['solved'] for k in common)
        losses = sum(bool(G['rows'][k]['solved']) and not RL['rows'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), rl_only=wins, g_only=losses, sign_test_p=r3.sign_test(wins, losses))
    s['decision'] = decision(s['arms'])
    plan = root / PLAN
    s['frozen_rule'] = json.loads(plan.read_text()).get('decision_rule') if plan.exists() else 'plan not written'
    s['disclosure'] = r3.disclosure()
    s['design_disclosure'] = DESIGN_DISCLOSURE
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}', '', '| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated/case | '
           'prompt/case | prefill computed/case | total compute/case | wall s | Wh | Wh/solved |',
           '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k, pol in ARMS.items():
        a = s['arms'][k]
        out.append(f"| {k} | {pol} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong_all_attempts', 'abstain', 'generated_per_case', 'prompt_per_case',
            'prefill_compute_per_case', 'total_compute_per_case', 'wall_seconds', 'wh', 'wh_per_solved')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired: RL-only solved {p['rl_only']}, G-only {p['g_only']}, exact sign test p = {p['sign_test_p']:.4g}."]
    out += ['', '## Escalation and relay', '', '| arm | answered by escalation (slot >= 4) | solved | answered by relayed agents '
            '| solved | relayed agents started |', '|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        out.append(f'| {k} | ' + ' | '.join(fmt(a.get(c)) for c in ('escalation_answered', 'escalation_solved',
                                                                       'relayed_answered', 'relayed_solved', 'relayed_agents')) + ' |')
    out += ['', 'Total compute = generated + computed prefill (server counters, all segments).', '',
            '## Decision (complete inputs, unrounded values)', '', f"Rule: {s['frozen_rule']}", '',
            f"Evaluation: {json.dumps(s['decision'])}", '', '## Wrong answers over all attempts and wasted work', '']
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
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['RL_replaces_G'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
