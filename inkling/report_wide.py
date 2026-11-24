#!/usr/bin/env python3
"""Report for study swarm-wide-hard20-v1 (SWARM_WIDE_HARD20_PLAN.json): G = roll12cancel (generic default) vs
W = roll12wide (work-conserving widening, Fable round 4 idea 1) on a fresh corpus, each arm run alone by
inkling/arms.py. Writes results/swarm-wide-hard20-v1/{REPORT.md, report.json}.

Validation is shared with report_round3_hard17 / report_relay_swarm (frozen resume rule, accounting validity for every
segment directory incl. input-work counters and Wh, embedded plan equal to the frozen plan file, wrong answers over
ALL attempts, wasted work, exact UTC window). Decision (complete inputs only, unrounded, wall in integer
microseconds): W replaces G if W has 0 wrong answers over all attempts, W solved >= G solved - 2, and
100 x W wall <= 95 x G wall. Reported as facts (not gated here): server generation tokens and total compute W/G,
GPU Wh W/G, Wh per solved, p90 judge latency, max widths reached and when.

usage: report_wide.py [--root DIR] [--out DIR] [--g DIR] [--w DIR]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402
import report_relay_swarm as rs  # noqa: E402  (input-work validation)

STUDY = 'swarm-wide-hard20-v1'
PLAN = 'SWARM_WIDE_HARD20_PLAN.json'
ARMS = dict(G='roll12cancel', W='roll12wide')
NOISE = 2
DESIGN_DISCLOSURE = (
    'Design notes: (1) G and W run the same agents with the same prompts and seeds (slots pair exactly); W only moves '
    'start times: once no case waits for admission, a case with at least one failed agent may start its next slots up '
    'to 8 in flight, oldest case first, least-loaded node first, keeping 2 permits per node free for judges; widened '
    'slots may run on another node than in G; (2) the trigger is slot occupancy and failure counts, never elapsed time '
    'and never task content; (3) the plan\'s code_sha256 pins are records checked by review, not enforced by the runner.')


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


def judge_latencies(rows):
    """Seconds from an agent's end to its verdict (judged_s - finished_s) for every judged agent."""
    return [a['judged_s'] - a['finished_s'] for r in rows for a in r['agents']
            if isinstance(a.get('judged_s'), (int, float)) and isinstance(a.get('finished_s'), (int, float))]


def summarize(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
    rows = list(a['rows'].values())
    n, solved, wrong = len(rows), sum(bool(r['solved']) for r in rows), sum(bool(r['wrong']) for r in rows)
    gen, wh, work = a['server_tokens'], a['wh'], a['input_work']
    compute = gen + work['prefill_compute_tokens'] if gen is not None and work['prefill_compute_tokens'] is not None else None
    lat = judge_latencies(rows)
    widths = [r['max_in_flight'] for r in rows if 'max_in_flight' in r]
    widened = [r for r in rows if r.get('widened_agents')]
    return dict(status=a['status'], reasons=a['reasons'], segments=a['segments'], cases=n, solved=solved, wrong=wrong,
                wrong_all_attempts=a['wrong_all_attempts'], wrong_attempts=a['wrong_attempts'], wasted_work=a['wasted_work'],
                abstain=sum(not r['answered'] for r in rows), unresolved=len(a['unresolved']),
                generated_tokens=gen, prompt_tokens=work['prompt_tokens'], prefill_compute_tokens=work['prefill_compute_tokens'],
                total_compute_tokens=compute, generated_per_case=gen / n if gen is not None and n else None,
                wall_seconds=a['window_seconds'], wall_us=a['window_us'], wh=wh,
                wh_per_solved=wh / solved if wh is not None and solved else None,
                judge_latency_median=r3.median(lat), judge_latency_p90=r3.pct(lat, .9),
                max_in_flight_histogram={str(k): widths.count(k) for k in sorted(set(widths))} if widths else None,
                widened_cases=len(widened), widened_agents=sum(r.get('widened_agents') or 0 for r in rows),
                widened_at_s_median=r3.median([r['widened_at_s'] for r in widened if r.get('widened_at_s') is not None]),
                plan_sha256=a['plan_sha256'])


def wall_within(w_us, g_us, num=95, den=100):
    """W wall <= num/den x G wall, exactly in integer microseconds."""
    return w_us is not None and g_us is not None and g_us > 0 and den * w_us <= num * g_us


def decision(arms):
    G, W = arms['G'], arms['W']
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in arms.items() if a.get('status') != 'complete']
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(zero_wrong=W['wrong_all_attempts'] == 0, solved_within_noise=W['solved'] >= G['solved'] - NOISE,
                wall_at_most_95pct_of_G=wall_within(W['wall_us'], G['wall_us']))
    rule['W_replaces_G'] = all(rule.values())
    return rule


def ratio(x, y):
    return x / y if x is not None and y else None


def build(root, dirs):
    loaded = {k: load(dirs[k], root, ARMS[k]) for k in ARMS}
    s = dict(study=STUDY, policies=ARMS, arms={k: summarize(a) for k, a in loaded.items()})
    G, W = loaded['G'], loaded['W']
    if 'rows' in G and 'rows' in W:
        common = sorted(set(G['rows']) & set(W['rows']))
        wins = sum(bool(W['rows'][k]['solved']) and not G['rows'][k]['solved'] for k in common)
        losses = sum(bool(G['rows'][k]['solved']) and not W['rows'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), w_only=wins, g_only=losses, sign_test_p=r3.sign_test(wins, losses))
    sg, sw = s['arms']['G'], s['arms']['W']
    s['facts'] = dict(wall_ratio_w_over_g=ratio(sw.get('wall_us'), sg.get('wall_us')),
                      generated_tokens_ratio=ratio(sw.get('generated_tokens'), sg.get('generated_tokens')),
                      total_compute_ratio=ratio(sw.get('total_compute_tokens'), sg.get('total_compute_tokens')),
                      wh_ratio=ratio(sw.get('wh'), sg.get('wh')))
    s['decision'] = decision(s['arms'])
    plan = root / PLAN
    s['frozen_rule'] = json.loads(plan.read_text()).get('decision_rule') if plan.exists() else 'plan not written'
    s['disclosure'] = r3.disclosure()
    s['design_disclosure'] = DESIGN_DISCLOSURE
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}', '', '| arm | policy | status | cases | solved | wrong (all attempts) | abstain | generated | '
           'total compute | wall s | Wh | Wh/solved | judge latency p90 s |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k, pol in ARMS.items():
        a = s['arms'][k]
        out.append(f"| {k} | {pol} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong_all_attempts', 'abstain', 'generated_tokens', 'total_compute_tokens', 'wall_seconds',
            'wh', 'wh_per_solved', 'judge_latency_p90')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired: W-only solved {p['w_only']}, G-only {p['g_only']}, exact sign test p = {p['sign_test_p']:.4g}."]
    w = s['arms']['W']
    out += ['', '## Widening (W)', '']
    if 'widened_cases' in w:
        out += [f"- cases that widened: {w['widened_cases']}; widened agents: {w['widened_agents']}; median time to the "
                f"first widened start: {fmt(w['widened_at_s_median'])} s",
                f"- max agents in flight per case (histogram): {w['max_in_flight_histogram']}"]
    else:
        out.append(f"- {w['status']}")
    out += ['', f"Facts (W / G): {json.dumps(s['facts'])}", '', '## Decision (complete inputs, unrounded values)', '',
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
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['W_replaces_G'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
