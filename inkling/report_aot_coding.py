#!/usr/bin/env python3
"""Report for study coding-aot-v1: the generic Atom-of-Thoughts worker variant in the coding swarm.
  P = R2 (run_coding_earlystop.py, rolling width 2) with the plain agent code_xl   plan CODING_AOT_P_PLAN.json
  A = R2 with every agent AoT (code_aot: same per-agent 32,768-token budget, same agent count = equal compute cap)
                                                                                  plan CODING_AOT_A_PLAN.json
Runs runs/coding-aot-v1-{p,a}, each arm alone on the fleet via inkling/coding_arms.py. Writes
results/coding-aot-v1/{REPORT.md, report.json}. Atom of Thoughts: Teng et al. 2025 (arXiv 2502.12018,
github.com/qixucen/atom); the task-graph framing follows alkimiadev's taskgraph idea.

Validation per arm (any failure -> the arm is incomplete, never zero-filled): cases.json, summary.json and
metadata.json present; the embedded plan equals the frozen plan file; the plan is FROZEN, runs run_coding_earlystop.py
with early stop and rolling width 2, and every agent variant is the arm's (code_xl / code_aot); the run completed with no
controller errors and no source change; no agent row has an operational fault (run_agents72.operational_fault); the
case set is exactly the plan's corpus (split tasks, optional task_ids, x seeds); arm_accounting.json is valid
(report_round3_hard17.accounting: server generation tokens, idle after, per-node counters, UTC window), runner exit 0
and GPU Wh present; and no agent trace holds a transport-retry event (the pinned coding transport has none).
Pairing must be complete: both frozen plans agree on every field that defines the cases and the compute (matrix, seeds,
source revision and path, limits, scheduling, runner, agent seed offset, early stop, rolling, serving) and both arms
finished the same non-empty case set; otherwise the decision is incomplete.

Decision (complete inputs only, unrounded): AoT is adopted if A solved >= P solved + 3, A wrong <= P wrong, and A server
generation tokens <= 1.10 x P (compared as 100 x A <= 110 x P); otherwise not. A coding answer is a proposal that
passed the public feedback cases; it is wrong if it fails the hidden holdout cases (which no agent sees).

Transport: the pinned coding worker transport has NO completion retry in either variant, so a lost request is an
operational fault for both arms alike (the arms are identical there; no retry tokens exist to charge on either side).
An auxiliary AoT failure ends the AoT loop and the agent's final call still runs.

usage: report_aot_coding.py [--root DIR] [--out DIR] [--p DIR] [--a DIR] [--p-plan FILE] [--a-plan FILE]
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402
from run_agents72 import operational_fault  # noqa: E402

STUDY = 'coding-aot-v1'
ARMS = dict(P=dict(plan='CODING_AOT_P_PLAN.json', dir=f'runs/{STUDY}-p', variant='code_xl'),
            A=dict(plan='CODING_AOT_A_PLAN.json', dir=f'runs/{STUDY}-a', variant='code_aot'))
RUNNER, WIDTH = 'run_coding_earlystop.py', 2
MIN_GAIN, TOKEN_NUM, TOKEN_DEN = 3, 110, 100
PAIRED_FIELDS = ('matrix', 'source_revision', 'source_path', 'limits', 'scheduling', 'runner', 'agent_seed_offset',
                 'early_stop', 'rolling', 'serving')
RETRY_EVENTS = ('request_retry', 'request_retry_aborted')


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def plan_cases(root, plan):
    """The frozen plan's cases: the corpus tasks of its split (optional task_ids subset) x its seeds."""
    m = plan['matrix']
    tasks = [t['id'] for t in json.loads((root / m['tasks']).read_text())['tasks'] if t['split'] == m['split']]
    if m.get('task_ids'):
        tasks = [t for t in tasks if t in m['task_ids']]
    if len(set(tasks)) != m['tasks_count']:
        raise ValueError(f"{len(set(tasks))} tasks in the corpus split, plan says {m['tasks_count']}")
    return {(t, s) for s in m['seeds'] for t in tasks}


def traces(d):
    """Agent traces of a coding run directory (one <stem>.jsonl per agent, next to cases.json)."""
    return sorted(Path(d).glob('*.jsonl'))


def events(path):
    for line in Path(path).read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def load(root, d, plan_file, variant):
    d = Path(d) if Path(d).is_absolute() else root / d
    if not (d / 'cases.json').exists():
        return dict(status='not run', dir=str(d))
    reasons = []
    meta, summary, rows = read_json(d / 'metadata.json'), read_json(d / 'summary.json'), read_json(d / 'cases.json')
    if not isinstance(meta, dict):
        return dict(status='incomplete', dir=str(d), reasons=['metadata.json missing or unreadable'])
    if not isinstance(rows, list) or not isinstance(summary, list):
        return dict(status='incomplete', dir=str(d), reasons=['cases.json or summary.json missing or unreadable'])
    plan_path = Path(plan_file) if Path(plan_file).is_absolute() else root / plan_file
    plan = read_json(plan_path)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest() if plan_path.exists() else None
    if not isinstance(plan, dict):
        reasons.append(f'frozen plan file {plan_path.name} not found or unreadable')
    elif meta.get('protocol') != plan:
        reasons.append(f'embedded plan differs from {plan_path.name} (sha256 {plan_sha[:12]})')
    if isinstance(plan, dict):
        if plan.get('status') != 'FROZEN':
            reasons.append('plan is not FROZEN')
        if plan.get('runner') != RUNNER or not plan.get('early_stop') or plan.get('rolling') != dict(width=WIDTH):
            reasons.append(f'plan is not R2 ({RUNNER}, early stop, rolling width {WIDTH})')
        if not plan.get('agent_variants') or set(plan['agent_variants']) != {variant}:
            reasons.append(f"agent variants {sorted(set(plan.get('agent_variants') or []))}, expected only {variant}")
    if not meta.get('completed_utc') or meta.get('errors') or meta.get('source_changed_during_run') is not False:
        reasons.append(f"run not completed cleanly (completed_utc {bool(meta.get('completed_utc'))}, "
                       f"errors {len(meta.get('errors') or [])}, source_changed {meta.get('source_changed_during_run')})")
    faults = []
    for r in summary:
        try:
            reason = operational_fault(r)
        except (KeyError, TypeError) as exc:
            reason = f'row unreadable ({type(exc).__name__}: {exc})'
        if reason:
            faults.append(f"{r.get('task_id')} s{r.get('seed')} a{r.get('agent')}: {reason}")
    if faults:
        reasons.append(f'{len(faults)} agent row(s) with an operational fault: {faults[:3]}')
    cases = {(r['task_id'], r['seed']): dict(answered=bool(r.get('answered')), solved=bool(r.get('solved')),
                                             wrong=bool(r.get('answered') and not r.get('solved')),
                                             winner_agent=r.get('winner_agent')) for r in rows}
    if len(cases) != len(rows):
        reasons.append('a case appears twice in cases.json')
    if isinstance(plan, dict):
        try:
            expected = plan_cases(root, plan)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reasons.append(f'plan corpus unreadable: {exc}'[:200])
        else:
            if set(cases) != expected:
                reasons.append(f"cases differ from the plan's {len(expected)} ({len(expected - set(cases))} missing, "
                               f"{len(set(cases) - expected)} extra)")
    acct = r3.accounting([d])
    reasons += acct['accounting_problems']
    record = read_json(d / 'arm_accounting.json') or {}
    if record and record.get('runner_exit') != 0:
        reasons.append(f"runner exit {record.get('runner_exit')}")
    if acct['wh'] is None:
        reasons.append('GPU energy (Wh) missing')
    retry = Counter(e['type'] for t in traces(d) for e in events(t) if e.get('type') in RETRY_EVENTS)
    if retry:
        reasons.append(f'transport retry events found {dict(retry)} (the pinned coding transport has none)')
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, dir=str(d), plan=plan,
                plan_sha256=plan_sha, cases=cases, summary_rows=summary, accounting=acct,
                transport_retries=dict(retries=retry.get('request_retry', 0),
                                       retries_not_sent=retry.get('request_retry_aborted', 0)))


def summarize(a):
    out = {k: a[k] for k in ('status', 'reasons', 'dir', 'plan_sha256', 'transport_retries') if k in a}
    if 'cases' in a:
        vals = list(a['cases'].values())
        acct = a['accounting']
        solved = sum(c['solved'] for c in vals)
        out.update(cases=len(vals), solved=solved, wrong=sum(c['wrong'] for c in vals),
                   unanswered=sum(not c['answered'] for c in vals), generated_tokens=acct['server_tokens'],
                   generated_tokens_per_case=acct['server_tokens'] / len(vals) if acct['server_tokens'] is not None
                   and vals else None, wall_seconds=acct['wall_seconds'], window_seconds=acct['window_seconds'],
                   wh=acct['wh'], wh_per_solved=acct['wh'] / solved if acct['wh'] is not None and solved else None,
                   agents_started=len(a['summary_rows']))
    return out


def pairing(loaded):
    """Complete pairing: the same case-defining and compute-defining plan fields and the same non-empty case set."""
    problems = []
    plans = {k: loaded[k].get('plan') for k in ARMS}
    if all(isinstance(p, dict) for p in plans.values()):
        diff = [f for f in PAIRED_FIELDS if plans['P'].get(f) != plans['A'].get(f)]
        if diff:
            problems.append(f'frozen plans differ in {diff}')
    else:
        problems.append('a frozen plan is missing')
    cases = {k: set(loaded[k].get('cases') or {}) for k in ARMS}
    if cases['P'] != cases['A']:
        problems.append(f"case sets differ (P {len(cases['P'])}, A {len(cases['A'])}, common {len(cases['P'] & cases['A'])})")
    if not cases['P'] & cases['A']:
        problems.append('no paired cases')
    return problems


def aot_mechanism(a):
    """Per started code_aot agent: its puzzle_end 'aot' summary."""
    stats = Counter()
    winners = {(k[0], k[1], c['winner_agent']) for k, c in a['cases'].items() if c['answered']}
    for r in a['summary_rows']:
        path = Path(a['dir']) / Path(str(r.get('events') or '')).name
        end = {}
        if path.is_file():
            for e in events(path):
                if e.get('type') == 'puzzle_end':
                    end = e
        summary = end.get('aot')
        if not isinstance(summary, dict):
            stats['no_summary'] += 1
            continue
        rounds = summary.get('rounds') or []
        stats['agents'] += 1
        stats['round1_' + ((rounds[0].get('stop') or 'decomposed') if rounds else 'none')] += 1
        stats['aux_failure'] += any(x.get('stop') == 'aux_failure' for x in rounds)
        stats['contracted'] += bool(summary.get('contracted'))
        stats['with_facts'] += bool(summary.get('facts'))
        stats['facts'] += summary.get('facts') or 0
        stats['winners_with_facts'] += bool(summary.get('facts')) and (r.get('task_id'), r.get('seed'), r.get('agent')) in winners
    return dict(stats)


def decision(arms, pairing_problems):
    P, A = arms['P'], arms['A']
    why = [f"{k}: {a['status']}" + (f" ({'; '.join(a.get('reasons') or [])})" if a.get('reasons') else '')
           for k, a in arms.items() if a.get('status') != 'complete']
    why += [f'pairing: {p}' for p in pairing_problems]
    if why:
        return f"incomplete - {' | '.join(why)}"
    rule = dict(solved_at_least_plain_plus_3=A['solved'] >= P['solved'] + MIN_GAIN, wrong_at_most_plain=A['wrong'] <= P['wrong'],
                tokens_at_most_110pct=TOKEN_DEN * A['generated_tokens'] <= TOKEN_NUM * P['generated_tokens'])
    rule['AoT_adopted'] = all(rule.values())
    return rule


def build(root, dirs, plans=None):
    plans = plans or {k: v['plan'] for k, v in ARMS.items()}
    loaded = {k: load(root, dirs[k], plans[k], ARMS[k]['variant']) for k in ARMS}
    s = dict(study=STUDY, arms={k: summarize(a) for k, a in loaded.items()})
    s['pairing_problems'] = pairing(loaded)
    P, A = loaded['P'], loaded['A']
    if 'cases' in P and 'cases' in A:
        common = sorted(set(P['cases']) & set(A['cases']))
        wins = sum(A['cases'][k]['solved'] and not P['cases'][k]['solved'] for k in common)
        losses = sum(P['cases'][k]['solved'] and not A['cases'][k]['solved'] for k in common)
        s['paired'] = dict(cases=len(common), aot_only=wins, plain_only=losses, sign_test_p=r3.sign_test(wins, losses))
    if 'cases' in A:
        s['mechanism'] = aot_mechanism(A)
    s['decision'] = decision(s['arms'], s['pairing_problems'])
    s['frozen_rules'] = {k: (A_or_P.get('plan') or {}).get('decision_rule', 'plan not written')
                         for k, A_or_P in loaded.items()}
    return s


def markdown(s):
    fmt = r3.fmt
    out = [f'# {STUDY}: Atom of Thoughts in the coding swarm (R2)', '',
           '| arm | status | cases | solved | wrong | unanswered | generated | generated/case | wall s | Wh | Wh/solved | '
           'retries |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        out.append(f"| {k} ({ARMS[k]['variant']}) | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'solved', 'wrong', 'unanswered', 'generated_tokens', 'generated_tokens_per_case', 'wall_seconds',
            'wh', 'wh_per_solved')) + f" | {fmt((a.get('transport_retries') or {}).get('retries'))} |")
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if s['pairing_problems']:
        out += ['', f"Pairing incomplete: {'; '.join(s['pairing_problems'])}"]
    if 'paired' in s:
        p = s['paired']
        out += ['', f"Paired ({p['cases']} cases): AoT-only solved {p['aot_only']}, plain-only {p['plain_only']}, exact "
                    f"sign test p = {p['sign_test_p']:.4g}."]
    if 'mechanism' in s:
        out += ['', f"AoT agents: {json.dumps(s['mechanism'])}"]
    out += ['', '## Decision (complete inputs, unrounded values)', '', f"Rules: {json.dumps(s['frozen_rules'])}", '',
            f"Evaluation: {json.dumps(s['decision'])}", '', '## Disclosures', '',
            'Transport: the pinned coding worker transport has no completion retry in either variant (code_xl and '
            'code_aot are identical there): a lost request is an operational fault for both arms, and no retry tokens '
            'exist to charge on either side. An auxiliary AoT failure ends the AoT loop; the agent\'s final call still '
            'runs. Acceptance is the public feedback cases; the hidden holdout cases only score. Both arms use the same '
            'worker source revision, per-agent completion-token budget (32,768) and agent count, so the compute cap is '
            'equal; tokens are server counters over each arm\'s window.', '',
            'Atom of Thoughts: Teng et al. 2025 (arXiv 2502.12018, github.com/qixucen/atom); the task-graph framing follows '
            "alkimiadev's taskgraph idea.", '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--out', type=Path)
    for k, v in ARMS.items():
        p.add_argument('--' + k.lower(), default=v['dir'])
        p.add_argument(f'--{k.lower()}-plan', default=v['plan'])
    a = p.parse_args(argv)
    root = a.root.resolve()
    s = build(root, {k: getattr(a, k.lower()) for k in ARMS}, {k: getattr(a, f'{k.lower()}_plan') for k in ARMS})
    out = a.out or root / 'results' / STUDY
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(out=str(out), arms={k: v['status'] for k, v in s['arms'].items()},
                          decision=s['decision'] if isinstance(s['decision'], str) else s['decision']['AoT_adopted'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
