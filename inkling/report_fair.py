#!/usr/bin/env python3
"""Report for study swarm-fair-hard22-v1 (SWARM_FAIR_HARD22_PLAN.json): W = roll12wide (default) vs F = roll12fair
(water-filling admission, Fable round 5 idea 2) on a fresh corpus, each arm run alone by inkling/arms.py, same agents,
prompts and seeds (slots pair exactly). Writes results/swarm-fair-hard22-v1/{REPORT.md, report.json}.

Validation is report_wide's (frozen resume rule, accounting validity for every segment directory incl. input-work
counters and Wh, embedded plan equal to the frozen plan file, wrong answers over ALL attempts, wasted work, exact UTC
window). Pairing must be complete: both arms finished the same non-empty case set, else the decision is incomplete.
Decision (Fable; complete inputs only, unrounded, wall in integer microseconds): F replaces W if F has 0 wrong answers
over all attempts, F solved >= W solved - 2, 100 x F wall <= 95 x W wall and F server generation tokens <= W server
generation tokens. Reported as facts (not gated): mean, median and p90 time to an answer, measured both from the
case's own start (answer_seconds) and from the segment start (case_start_s + answer_seconds; rows written before
case_start_s existed have no such value); GPU Wh, total compute, max agents in flight per case, time to the first
failure.

usage: report_fair.py [--root DIR] [--out DIR] [--w DIR] [--f DIR]
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402
import report_relay_swarm as rs  # noqa: E402  (input-work validation)
import report_wide as rw  # noqa: E402  (arm summary)

STUDY = 'swarm-fair-hard22-v1'
PLAN = 'SWARM_FAIR_HARD22_PLAN.json'
ARMS = dict(W='roll12wide', F='roll12fair')
NOISE = 2
DESIGN_DISCLOSURE = (
    'Design notes: (1) W and F run the same agents with the same prompts and seeds (slot s of a case has the same seed '
    'in both arms); F only changes which case gets a free agent slot and when: every case is open from the start, a free '
    'slot (a node below its cap minus 2 permits kept for judges) goes to the case with the fewest agents in flight (ties: '
    'fewest started, then the earlier case), at most 4 in flight before the case\'s first failed agent and 8 after, never '
    'beyond 12 agents; an F agent may run on another node than in W; (2) the rule reads slot counts and failure counts '
    'only, never elapsed time or task content; (3) time to answer from the segment start is comparable between arms '
    'only within one segment (a resumed segment restarts its clock).')


def load(path, root, policy):
    a = r3.load_arm(path, root, policy, PLAN)
    if 'arm' not in a:
        return a
    work, problems = rs.input_work(a)
    if a.get('wh') is None:
        problems.append('GPU energy (Wh) missing for a segment')
    if problems:
        a = dict(a, status='incomplete', reasons=a['reasons'] + problems)
    return dict(a, input_work=work)


def stats(values):
    values = [x for x in values if isinstance(x, (int, float))]
    if not values:
        return None
    return dict(n=len(values), mean=statistics.fmean(values), median=r3.median(values), p90=r3.pct(values, .9))


def answer_times(a):
    rows = [r for r in a['rows'].values() if r.get('answered') and isinstance(r.get('answer_seconds'), (int, float))]
    return dict(from_case_start=stats([r['answer_seconds'] for r in rows]),
                from_segment_start=stats([r['case_start_s'] + r['answer_seconds'] for r in rows
                                          if isinstance(r.get('case_start_s'), (int, float))]))


def summarize(a):
    s = rw.summarize(a)
    if 'rows' in a:
        rows = list(a['rows'].values())
        s['answer_time_s'] = answer_times(a)
        s['first_failure_s_median'] = r3.median([r['first_failure_s'] for r in rows
                                                 if isinstance(r.get('first_failure_s'), (int, float))])
    return s


def pairing(loaded):
    rows = {k: set(loaded[k].get('rows') or {}) for k in ARMS}
    problems = []
    if rows['W'] != rows['F']:
        problems.append(f"case sets differ (W {len(rows['W'])}, F {len(rows['F'])}, common {len(rows['W'] & rows['F'])})")
    if not rows['W'] & rows['F']:
        problems.append('no paired cases')
    return problems


def decision(arms, pairing_problems):
    W, F = arms['W'], arms['F']
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in arms.items() if a.get('status') != 'complete']
    why += [f'pairing: {p}' for p in pairing_problems]
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(zero_wrong=F['wrong_all_attempts'] == 0, solved_within_noise=F['solved'] >= W['solved'] - NOISE,
                wall_at_most_95pct_of_W=rw.wall_within(F['wall_us'], W['wall_us']),
                tokens_at_most_100pct_of_W=(F['generated_tokens'] is not None and W['generated_tokens'] is not None
                                            and F['generated_tokens'] <= W['generated_tokens']))
    rule['F_replaces_W'] = all(rule.values())
    return rule


def build(root, dirs):
    loaded = {k: load(dirs[k], root, ARMS[k]) for k in ARMS}
    s = dict(study=STUDY, policies=ARMS, arms={k: summarize(a) for k, a in loaded.items()})
    s['pairing_problems'] = pairing(loaded)
    W, F = loaded['W'], loaded['F']
    if 'rows' in W and 'rows' in F:
        common = sorted(set(W['rows']) & set(F['rows']))
        wins = sum(bool(F['rows'][k]['solved']) and not W['rows'][k]['solved'] for k in common)
        losses = sum(bool(W['rows'][k]['solved']) and not F['rows'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), f_only=wins, w_only=losses, sign_test_p=r3.sign_test(wins, losses))
    sw, sf = s['arms']['W'], s['arms']['F']
    s['facts'] = dict(wall_ratio_f_over_w=rw.ratio(sf.get('wall_us'), sw.get('wall_us')),
                      generated_tokens_ratio=rw.ratio(sf.get('generated_tokens'), sw.get('generated_tokens')),
                      total_compute_ratio=rw.ratio(sf.get('total_compute_tokens'), sw.get('total_compute_tokens')),
                      wh_ratio=rw.ratio(sf.get('wh'), sw.get('wh')))
    s['decision'] = decision(s['arms'], s['pairing_problems'])
    plan = root / PLAN
    s['frozen_rule'] = json.loads(plan.read_text()).get('decision_rule') if plan.exists() else 'plan not written'
    s['disclosure'] = r3.disclosure()
    s['design_disclosure'] = DESIGN_DISCLOSURE
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}', '', '| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated | '
           'total compute | wall s | Wh | Wh/solved |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k, pol in ARMS.items():
        a = s['arms'][k]
        out.append(f"| {k} | {pol} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong_all_attempts', 'abstain', 'generated_tokens', 'total_compute_tokens', 'wall_seconds',
            'wh', 'wh_per_solved')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if s['pairing_problems']:
        out += ['', f"Pairing incomplete: {'; '.join(s['pairing_problems'])}"]
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired: F-only solved {p['f_only']}, W-only {p['w_only']}, exact sign test p = {p['sign_test_p']:.4g}."]
    out += ['', '## Time to an answer (s; mean / median / p90)', '']
    for k in ARMS:
        t = s['arms'][k].get('answer_time_s') or {}
        for basis in ('from_case_start', 'from_segment_start'):
            x = t.get(basis)
            out.append(f"- {k} {basis.replace('_', ' ')}: " + (f"{fmt(x['mean'])} / {fmt(x['median'])} / {fmt(x['p90'])} "
                                                                f"(n = {x['n']})" if x else '-'))
    for k in ARMS:
        a = s['arms'][k]
        if 'max_in_flight_histogram' in a:
            out.append(f"- {k} max agents in flight per case: {a['max_in_flight_histogram']}"
                       + (f"; median time to the first failure {fmt(a.get('first_failure_s_median'))} s"
                          if a.get('first_failure_s_median') is not None else ''))
    out += ['', f"Facts (F / W): {json.dumps(s['facts'])}", '', '## Decision (complete inputs, unrounded values)', '',
            f"Rule: {s['frozen_rule']}", '', f"Evaluation: {json.dumps(s['decision'])}", '',
            '## Wrong answers over all attempts and wasted work', '']
    for k in ARMS:
        a = s['arms'][k]
        if 'wrong_attempts' not in a:
            continue
        out.append(f"- {k}: {a['wrong_all_attempts']} wrong attempt(s)" +
                   (f": {json.dumps(a['wrong_attempts'])}" if a['wrong_attempts'] else ''))
        for x in a['wasted_work']:
            out.append(f"  - wasted segment {x['dir']}: server tokens {fmt(x.get('server_tokens'))}, wall "
                       f"{fmt(x.get('wall_seconds'))} s, {fmt(x.get('wh'))} Wh; "
                       + ('no case rows' if x.get('no_case_rows') else f"superseded cases {x['superseded_cases']}"))
    out += ['', '## Disclosures', '', s['disclosure'], '', s['design_disclosure'], '',
            'Idea: IDEAS-swarm-round5-fable.md, idea 2 (water-filling admission).', '']
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
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['F_replaces_W'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
