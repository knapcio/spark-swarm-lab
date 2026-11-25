#!/usr/bin/env python3
"""Report for a no-provided-tests coding study: three R2 arms on the same cases and seeds.

  public      the default: agents see the statement with its public examples; a proposal is accepted when it passes the
              feedback cases (run_coding_earlystop.py without `acceptance`)
  self_tests  no examples shown; accepted when the agent's own test cases pass in the CPU sandbox
  judge       no examples shown; accepted when the generic protocol judge says {"valid": true}

Scoring is the hidden tests in every arm: a case is solved if its winner passes every hidden case (for the public arm the
winner passed the feedback cases by construction, so that is its holdout result). Per arm: solved / wrong (answered,
fails the hidden tests) / unanswered, server and client tokens per case, judge tokens, arm wall, GPU Wh and Wh per solved,
stop time, agents started, and the acceptance quality over every finished agent (accepted and correct, accepted and wrong,
rejected but correct). Paired solved and answered counts against the public arm on the same cases, exact sign test.

Cost disclosure: the solver budget is the same in every arm; the judge arm adds, per parsed proposal, up to 2 judge calls
and 8,192 completion tokens. Those tokens are inside the judge arm's server tokens, client tokens and GPU Wh and are also
reported separately (judge tokens per case; solver tokens per case = client minus judge).

Completeness: the comparison is made only when all three arms are present, every run finished cleanly (arm accounting
present, runner exit 0, no recorded errors, completed) and every arm's task/seed set equals the frozen set of its plan
(tasks file at the plan hash, split, task subset, seeds). Otherwise report.json says status "incomplete" with the reasons,
no paired comparison is made (never over an intersection) and the exit code is 1.

usage: inkling/report_notests.py [--public RUN] [--self-tests RUN] [--judge RUN] [--runs-dir runs] [--out DIR]
Writes OUT/report.json and OUT/tables.md and prints the tables.
"""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from report_hard4 import sign_test  # noqa: E402

ARMS = (('public', 'R2, public tests (default)'), ('self_tests', 'R2, no tests: own tests'),
        ('judge', 'R2, no tests: judge'))
DEFAULT_RUNS = dict(public='coding-notests-v1-public', self_tests='coding-notests-v1-self',
                    judge='coding-notests-v1-judge')
SAME_FIELDS = (('matrix',), ('agent_variants',), ('agent_seed_offset',), ('rolling',), ('stagger',), ('source_revision',),
               ('limits',), ('scheduling', 'concurrent_agents_per_node'), ('serving', 'container'),
               ('serving', 'image_id'), ('serving', 'mem_fraction'))
JUDGE_STAGES = ('judge', 'judge_forced')
JUDGE_MAX_CALLS, JUDGE_MAX_TOKENS = 2, 8192  # coding_forced.JUDGE_TOTAL (6,144 thinking + forced answer)
DISCLOSURE = (f'Budgets: the solver budget is identical in all arms. The judge arm adds, per parsed proposal, up to '
              f'{JUDGE_MAX_CALLS} judge calls and {JUDGE_MAX_TOKENS:,} completion tokens on the same server; they are '
              'included in its server and client tokens and GPU Wh and shown separately as judge tokens per case.')


def read(path):
    return json.loads(Path(path).read_text())


def trace(run_dir, events):
    """(puzzle_end, judge completion tokens) of one agent trace, located by name inside the run directory."""
    path = Path(run_dir) / Path(events).name
    end, judge = {}, 0
    if not path.exists():
        return None, 0
    for line in path.read_text(errors='replace').splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'puzzle_end':
            end = record
        elif record.get('type') == 'request_end' and record.get('stage') in JUDGE_STAGES:
            judge += (record.get('usage') or {}).get('completion_tokens', 0) or 0
    return end, judge


def plan_field(plan, keys):
    value = plan
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def arm(run_dir, mode):
    run_dir = Path(run_dir)
    meta = read(run_dir / 'metadata.json')
    plan = meta['protocol']
    cases = {(c['task_id'], c['seed']): c for c in read(run_dir / 'cases.json')}
    rows = read(run_dir / 'summary.json') if (run_dir / 'summary.json').exists() else []
    acct = read(run_dir / 'arm_accounting.json') if (run_dir / 'arm_accounting.json').exists() else None
    n = len(cases)
    quality = dict(finished=0, parsed=0, accepted=0, accepted_correct=0, accepted_wrong=0, rejected_correct=0,
                   self_tests_invalid=0, judge_unparsed=0, traces_missing=0)
    judge_tokens = 0
    for row in rows:
        if row.get('cancelled'):
            continue
        quality['finished'] += 1
        end, judge = trace(run_dir, row['events'])
        judge_tokens += judge
        if end is None:
            quality['traces_missing'] += 1
            continue
        if not end.get('parsed'):
            continue
        quality['parsed'] += 1
        accepted = bool(end.get('accepted')) if mode != 'public' else bool(end.get('feedback_pass'))
        correct = bool(end.get('feedback_pass')) and bool(end.get('holdout_pass'))
        quality['accepted'] += accepted
        quality['accepted_correct'] += accepted and correct
        quality['accepted_wrong'] += accepted and not correct
        quality['rejected_correct'] += (not accepted) and correct
        quality['self_tests_invalid'] += bool(end.get('self_tests_error'))
        quality['judge_unparsed'] += mode == 'judge' and end.get('judge_verdict') is None
    stops = sorted(c['stop_seconds'] for c in cases.values() if c.get('stop_seconds') is not None)
    solved = sum(bool(c['solved']) for c in cases.values())
    answered = sum(bool(c['answered']) for c in cases.values())
    server = acct['server']['total']['generation_tokens'] if acct else None
    wh = (acct.get('energy') or {}).get('total_wh') if acct else None
    summary = dict(
        run=run_dir.name, acceptance=plan.get('acceptance'), cases=n, solved=solved, wrong=answered - solved,
        unanswered=n - answered,
        server_tokens_per_case=round(server / n) if server is not None and n else None,
        client_tokens_per_case=round(sum(c.get('completion_tokens') or 0 for c in cases.values()) / n) if n else None,
        judge_tokens_per_case=round(judge_tokens / n) if n else None,
        solver_tokens_per_case=round((sum(c.get('completion_tokens') or 0 for c in cases.values()) - judge_tokens) / n)
        if n else None,
        wall_seconds=acct['runner_wall_seconds'] if acct else meta.get('batch_wall_seconds'),
        gpu_wh=wh, wh_per_solved=round(wh / solved, 3) if wh and solved else None,
        stop_median=round(statistics.median(stops)) if stops else None,
        stop_p90=round(stops[min(len(stops) - 1, int(.9 * len(stops)))]) if stops else None,
        started_per_case=round(sum(c['started'] for c in cases.values()) / n, 2) if n else None,
        never_started=sum(c['never_started'] for c in cases.values()), acceptance_quality=quality,
        runner_exit=acct.get('runner_exit') if acct else None, errors=len(meta.get('errors') or []),
        accounting=acct is not None, completed=bool(meta.get('completed_utc')))
    return cases, summary, plan


def run_problems(mode, summary):
    problems = []
    if not summary['accounting']:
        problems.append(f'{mode}: no arm_accounting.json')
    elif summary['runner_exit'] != 0:
        problems.append(f'{mode}: runner exit {summary["runner_exit"]}')
    if summary['errors']:
        problems.append(f'{mode}: {summary["errors"]} runner errors recorded')
    if not summary['completed']:
        problems.append(f'{mode}: run not completed')
    return problems


def frozen_cases(plan, root):
    """(task, seed) set of the plan's frozen matrix, or (None, reason)."""
    matrix = plan.get('matrix') or {}
    path = Path(root) / str(matrix.get('tasks'))
    if not path.exists():
        return None, f'tasks file {matrix.get("tasks")} not found'
    if hashlib.sha256(path.read_bytes()).hexdigest() != matrix.get('tasks_sha256'):
        return None, f'tasks file {matrix.get("tasks")} does not match the plan hash'
    tasks = [t['id'] for t in read(path)['tasks'] if t.get('split') == matrix.get('split')]
    if matrix.get('task_ids'):
        tasks = [t for t in tasks if t in matrix['task_ids']]
    if len(tasks) != matrix.get('tasks_count'):
        return None, f'{len(tasks)} tasks in the frozen split, plan says {matrix.get("tasks_count")}'
    return {(t, s) for t in tasks for s in matrix.get('seeds') or []}, None


def consistency(plans):
    """Fields that must be equal across the arms, and the acceptance field each arm must carry."""
    problems = []
    names = list(plans)
    for keys in SAME_FIELDS:
        values = {name: plan_field(plans[name], keys) for name in names}
        if len({json.dumps(v, sort_keys=True) for v in values.values()}) > 1:
            problems.append(f"{'.'.join(keys)} differs: " + ', '.join(f'{k}={json.dumps(v)[:60]}' for k, v in values.items()))
    for name, plan in plans.items():
        expected = None if name == 'public' else name
        if plan.get('acceptance') != expected:
            problems.append(f'{name}: plan acceptance is {plan.get("acceptance")!r}, expected {expected!r}')
    return problems


def paired(base, other):
    """Only for complete studies: both arms hold exactly the frozen case set (never an intersection)."""
    if set(base) != set(other):
        raise ValueError('paired comparison needs identical case sets')
    keys = sorted(base)
    wins = sum(other[k]['solved'] and not base[k]['solved'] for k in keys)
    losses = sum(base[k]['solved'] and not other[k]['solved'] for k in keys)
    answered_wins = sum(other[k]['answered'] and not base[k]['answered'] for k in keys)
    answered_losses = sum(base[k]['answered'] and not other[k]['answered'] for k in keys)
    return dict(cases=len(keys), wins=wins, losses=losses, p=round(sign_test(wins, losses), 4),
                answered_wins=answered_wins, answered_losses=answered_losses,
                answered_p=round(sign_test(answered_wins, answered_losses), 4))


def fmt(value, spec=','):
    return '-' if value is None else format(value, spec)


def tables(res):
    labels = dict(ARMS)
    lines = []
    if res['status'] != 'complete':
        lines += ['**INCOMPLETE: no comparison is made.**', ''] + [f'- {x}' for x in res['problems']] + ['']
    lines += ['| Arm | Solved | Wrong | No answer | Server tokens/case | Solver tokens/case | Judge tokens/case | Wall | '
              'GPU Wh | Wh per solved | Stop median / p90 | Agents started/case |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, _ in ARMS:
        if name not in res['arms']:
            continue
        a = res['arms'][name]
        wall = f"{a['wall_seconds']:,.0f} s" if a['wall_seconds'] is not None else '-'
        lines.append(f"| {labels[name]} | **{a['solved']}**/{a['cases']} | {a['wrong']} | {a['unanswered']} | "
                     f"{fmt(a['server_tokens_per_case'])} | {fmt(a['solver_tokens_per_case'])} | "
                     f"{fmt(a['judge_tokens_per_case'])} | {wall} | {fmt(a['gpu_wh'])} | {fmt(a['wh_per_solved'], '.2f')} | "
                     f"{fmt(a['stop_median'])} / {fmt(a['stop_p90'])} s | {fmt(a['started_per_case'])} |")
    lines += ['', '| Arm | Finished agents | Parsed | Accepted | Accepted, correct | Accepted, wrong | Rejected, correct | '
                  'Invalid own tests | Judge unparsed |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, _ in ARMS:
        if name in res['arms']:
            q = res['arms'][name]['acceptance_quality']
            lines.append(f"| {labels[name]} | {q['finished']} | {q['parsed']} | {q['accepted']} | {q['accepted_correct']} | "
                         f"{q['accepted_wrong']} | {q['rejected_correct']} | {q['self_tests_invalid']} | {q['judge_unparsed']} |")
    lines += ['', DISCLOSURE, '']
    for name, p in res['paired'].items():
        lines.append(f"{labels[name]} vs public tests, paired on {p['cases']} cases: solved +{p['wins']} / -{p['losses']} "
                     f"(p = {p['p']:.2g}); answered +{p['answered_wins']} / -{p['answered_losses']} "
                     f"(p = {p['answered_p']:.2g}).")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--public', default=DEFAULT_RUNS['public'])
    p.add_argument('--self-tests', default=DEFAULT_RUNS['self_tests'])
    p.add_argument('--judge', default=DEFAULT_RUNS['judge'])
    p.add_argument('--runs-dir', type=Path, default=ROOT / 'runs')
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'coding-notests-v1')
    p.add_argument('--root', type=Path, default=ROOT, help='tree the plans\' matrix paths are relative to')
    a = p.parse_args(argv)
    names = dict(public=a.public, self_tests=a.self_tests, judge=a.judge)
    data, problems = {}, []
    for mode, run in names.items():
        run_dir = Path(run) if Path(run).is_absolute() else a.runs_dir / run
        if not all((run_dir / f).exists() for f in ('cases.json', 'metadata.json')):
            problems.append(f'{mode}: arm {run} missing (no cases.json / metadata.json)')
            continue
        data[mode] = arm(run_dir, mode)
        problems += run_problems(mode, data[mode][1])
        expected, reason = frozen_cases(data[mode][2], a.root)
        if expected is None:
            problems.append(f'{mode}: {reason}')
        elif set(data[mode][0]) != expected:
            missing, extra = len(expected - set(data[mode][0])), len(set(data[mode][0]) - expected)
            problems.append(f'{mode}: task/seed set is not the frozen {len(expected)} ({missing} missing, {extra} extra)')
    problems += consistency({m: d[2] for m, d in data.items()}) if len(data) > 1 else []
    complete = not problems and len(data) == len(names)
    res = dict(status='complete' if complete else 'incomplete', problems=problems, disclosure=DISCLOSURE,
               arms={m: d[1] for m, d in data.items()},
               paired={m: paired(data['public'][0], d[0]) for m, d in data.items() if m != 'public'} if complete else {})
    md = tables(res)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    (a.out / 'tables.md').write_text(md)
    print(md)
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
