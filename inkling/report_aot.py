#!/usr/bin/env python3
"""Report for study swarm-aot-hard21-v1: the generic Atom-of-Thoughts worker variant in the swarm.
  P = roll12wide with the plain agent (xl_forced_original)      plan SWARM_AOT_HARD21_P_PLAN.json
  A = roll12wide with every agent AoT (xl_aot, same per-agent token budget and agent count = equal compute cap)
                                                                plan SWARM_AOT_HARD21_A_PLAN.json
Runs runs/swarm-aot-hard21-v1-{p,a}-roll12wide[-resumeN], each arm alone via inkling/arms.py. Writes
results/swarm-aot-hard21-v1/{REPORT.md, report.json}. Atom of Thoughts: Teng et al. 2025 (arXiv 2502.12018,
github.com/qixucen/atom); the task-graph framing follows alkimiadev's taskgraph idea.

Validation is shared with report_round3_hard17 / report_wide (frozen resume rule, accounting validity for every segment
directory incl. input-work counters and Wh, each arm's embedded plan equal to its frozen plan file, wrong answers over
ALL attempts, wasted work, exact UTC window). Decision (complete inputs only, unrounded): AoT is adopted if A has 0
wrong answers over all attempts, A solved >= P solved + 3, and A server generation tokens <= 1.10 x P (compared as
100 x A <= 110 x P); otherwise not. Mechanism (A): agents whose decomposition parsed, that contracted, the facts
handed to the final call (from each agent's puzzle_end 'aot' summary).

usage: report_aot.py [--root DIR] [--out DIR] [--p DIR] [--a DIR]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402
import report_wide as rw  # noqa: E402  (arm summary with input work and Wh)

STUDY = 'swarm-aot-hard21-v1'
POLICY = 'roll12wide'
ARMS = dict(P=dict(plan='SWARM_AOT_HARD21_P_PLAN.json', dir=f'runs/{STUDY}-p-{POLICY}'),
            A=dict(plan='SWARM_AOT_HARD21_A_PLAN.json', dir=f'runs/{STUDY}-a-{POLICY}'))
MIN_GAIN, TOKEN_NUM, TOKEN_DEN = 3, 110, 100


def load(path, root, plan):
    a = r3.load_arm(path, root, POLICY, plan)
    if 'arm' not in a:
        return a
    work, problems = rw.rs.input_work(a)
    if a.get('wh') is None:
        problems.append('GPU energy (Wh) missing for a segment')
    if problems:
        a = dict(a, status='incomplete', reasons=a['reasons'] + problems)
    return dict(a, input_work=work)


def aot_mechanism(a):
    """Per started agent of the AoT arm: its puzzle_end 'aot' summary (decomposed, contracted, facts)."""
    stats = Counter()
    for (task_id, seed), (seg, row) in a['arm']['latest'].items():
        for agent in row.get('agents') or []:
            if not agent.get('started', True) or agent.get('cancelled'):
                continue
            end = trace_end(Path(seg) / 'agents' / f"{task_id}-s{seed}-{POLICY}-a{agent['slot']}.jsonl")
            summary = end.get('aot')
            if not isinstance(summary, dict):
                stats['no_summary'] += 1
                continue
            rounds = summary.get('rounds') or []
            stats['agents'] += 1
            stats['round1_' + ((rounds[0].get('stop') or 'decomposed') if rounds else 'none')] += 1
            stats['contracted'] += bool(summary.get('contracted'))
            stats['with_facts'] += bool(summary.get('facts'))
            stats['facts'] += summary.get('facts') or 0
            stats['accepted_with_facts'] += bool(summary.get('facts')) and agent.get('verdict') is True
    return dict(stats)


def trace_end(path):
    if not path.exists():
        return {}
    end = {}
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'puzzle_end':
            end = event
    return end


def decision(arms):
    P, A = arms['P'], arms['A']
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in arms.items() if a.get('status') != 'complete']
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(zero_wrong=A['wrong_all_attempts'] == 0, solved_at_least_plain_plus_3=A['solved'] >= P['solved'] + MIN_GAIN,
                tokens_at_most_110pct=(A['generated_tokens'] is not None and P['generated_tokens'] is not None
                                       and TOKEN_DEN * A['generated_tokens'] <= TOKEN_NUM * P['generated_tokens']))
    rule['AoT_adopted'] = all(rule.values())
    return rule


def build(root, dirs):
    loaded = {k: load(dirs[k], root, ARMS[k]['plan']) for k in ARMS}
    s = dict(study=STUDY, arms={k: rw.summarize(a) for k, a in loaded.items()})
    P, A = loaded['P'], loaded['A']
    if 'rows' in P and 'rows' in A:
        common = sorted(set(P['rows']) & set(A['rows']))
        wins = sum(bool(A['rows'][k]['solved']) and not P['rows'][k]['solved'] for k in common)
        losses = sum(bool(P['rows'][k]['solved']) and not A['rows'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), aot_only=wins, plain_only=losses, sign_test_p=r3.sign_test(wins, losses))
    if 'arm' in A:
        s['mechanism'] = aot_mechanism(A)
    s['decision'] = decision(s['arms'])
    s['frozen_rules'] = {k: (json.loads((root / v['plan']).read_text()).get('decision_rule')
                             if (root / v['plan']).exists() else 'plan not written') for k, v in ARMS.items()}
    s['disclosure'] = r3.disclosure()
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}: Atom of Thoughts in the swarm', '',
           '| arm | status | cases | solved | wrong (all attempts) | abstain | generated | total compute | wall s | Wh | '
           'Wh/solved |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong_all_attempts', 'abstain', 'generated_tokens', 'total_compute_tokens', 'wall_seconds',
            'wh', 'wh_per_solved')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired: AoT-only solved {p['aot_only']}, plain-only {p['plain_only']}, exact sign test p = "
                    f"{p['sign_test_p']:.4g}."]
    if 'mechanism' in s:
        out += ['', f"AoT agents: {json.dumps(s['mechanism'])}"]
    out += ['', '## Decision (complete inputs, unrounded values)', '', f"Rules: {json.dumps(s['frozen_rules'])}", '',
            f"Evaluation: {json.dumps(s['decision'])}", '', '## Disclosures', '', s['disclosure'], '',
            'Atom of Thoughts: Teng et al. 2025 (arXiv 2502.12018, github.com/qixucen/atom); the task-graph framing follows '
            "alkimiadev's taskgraph idea. Both arms run the same worker source revision; the AoT agent uses the plain "
            "agent's per-agent completion-token budget (32,768) and the same agent count, so the compute cap is equal.", '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path)
    for k, v in ARMS.items():
        p.add_argument('--' + k.lower(), default=v['dir'])
    a = p.parse_args(argv)
    root = a.root.resolve()
    s = build(root, {k: getattr(a, k.lower()) for k in ARMS})
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), arms={k: v['status'] for k, v in s['arms'].items()},
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['AoT_adopted'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
